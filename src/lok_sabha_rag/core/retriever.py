"""Retrieve evidence chunks from Qdrant."""

from __future__ import annotations

from collections import OrderedDict
import json
from dataclasses import dataclass, asdict, field, replace
from types import SimpleNamespace
from itertools import islice
from threading import RLock
from typing import Optional, List, Dict, Any

from qdrant_client import QdrantClient, models
from lok_sabha_rag.core.pdf_links import verified_pdf,verified_document
from lok_sabha_rag.core import kaggle_store
from lok_sabha_rag.core import debate_store
from lok_sabha_rag.core.temporal_retrieval import dates_in_year, balanced_groups

from lok_sabha_rag.config import (
    QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION,
    EMBEDDING_MODEL,
    DATA_DIR,
)


@dataclass(frozen=True)
class EvidenceItem:
    score: float
    chunk_id: str
    question_id: Optional[str]
    lok_no: Optional[int]
    session_no: Optional[int]
    ques_no: Optional[int]
    type: Optional[str]  # "Starred" | "Unstarred"
    asked_by: Optional[str]
    ministry: Optional[str]
    subject: Optional[str]
    pdf_filename: Optional[str]
    pdf_url: Optional[str]
    chunk_index: Optional[int]
    text: str
    house: str = 'lok_sabha'
    date: Optional[str] = None
    source_url: Optional[str] = None
    retrieval_method: str = 'dense'
    document_url: Optional[str] = None
    content_type: str = 'qa'
    debate_category: Optional[str] = None
    original_pages: Optional[str] = None
    transcript_status: Optional[str] = None


@dataclass
class EvidenceGroup:
    """A group of chunks from the same parliamentary question."""
    group_index: int
    question_id: Optional[str]
    lok_no: Optional[int]
    session_no: Optional[int]
    ques_no: Optional[int]
    type: Optional[str]  # "Starred" | "Unstarred"
    ministry: Optional[str]
    subject: Optional[str]
    asked_by: Optional[str]
    pdf_url: Optional[str]
    best_score: float
    chunks: List[EvidenceItem] = field(default_factory=list)
    total_chunks_available: int = 0   # how many chunks existed before trimming
    house: str = 'lok_sabha'
    date: Optional[str] = None
    source_url: Optional[str] = None
    retrieval_method: str = 'dense'
    document_url: Optional[str] = None
    content_type: str = 'qa'
    debate_category: Optional[str] = None
    original_pages: Optional[str] = None
    transcript_status: Optional[str] = None


def select_answer_chunks(matched, leading, limit):
    """Preserve the best retrieved passage, then add opening context within C."""
    ranked = sorted(matched, key=lambda c: c.score, reverse=True)
    candidates = ranked[:1] + leading[:1] + ranked[1:] + leading[1:]
    selected = []
    seen = set()
    for chunk in candidates:
        key = chunk.chunk_id or (chunk.chunk_index, chunk.text)
        if key in seen:
            continue
        seen.add(key)
        selected.append(chunk)
        if len(selected) == limit:
            break
    return sorted(selected, key=lambda c: c.chunk_index or 0)


def fuse_ranked(lists,limit):
    """RRF over question ranks, not incomparable cosine/BM25 score values."""
    scores={};chosen={}
    for items in lists:
        seen=set();rank=0
        for item in items:
            key=('DEBATE',item.question_id) if item.content_type=='debate' else kaggle_store.canonical(asdict(item)) if item.house=='rajya_sabha' else ('LS',item.question_id or item.chunk_id)
            if key in seen:continue
            seen.add(key);rank+=1
            scores[key]=scores.get(key,0)+1/(60+rank)
            chosen.setdefault(key,item)
    ordered=sorted(chosen,key=lambda k:scores[k],reverse=True)[:limit]
    return [replace(chosen[key],score=scores[key],retrieval_method='rank_fusion') for key in ordered]


def _build_filter(
    lok: Optional[int] = None,
    session: Optional[int] = None,
    ministry: Optional[str] = None,
    mp_names: Optional[List[str]] = None,
    record_year: Optional[int] = None,
    record_dates: Optional[List[str]] = None,
) -> Optional[models.Filter]:
    must = []
    if record_dates:
        must.append(models.FieldCondition(key='date', match=models.MatchAny(any=record_dates)))
    if record_year is not None:
        must.append(models.FieldCondition(key='date', match=models.MatchAny(any=dates_in_year(record_year))))
    if lok is not None:
        must.append(models.FieldCondition(key="lok_no", match=models.MatchValue(value=lok)))
    if session is not None:
        must.append(models.FieldCondition(key="session_no", match=models.MatchValue(value=session)))
    if ministry:
        must.append(models.FieldCondition(key="ministry", match=models.MatchValue(value=ministry)))
    if mp_names:
        # OR filter: match chunks where mp_names contains ANY of the provided names
        must.append(models.FieldCondition(
            key="mp_names",
            match=models.MatchAny(any=mp_names),
        ))
    return models.Filter(must=must) if must else None


def _safe_str(x) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    return s if s else None


def _extract_evidence(p, *, score: float = 0.0) -> EvidenceItem:
    """Convert a Qdrant point to an EvidenceItem."""
    pay = p.payload or {}
    src = pay.get("source", {}) or {}
    pdf_url = verified_pdf(pay) if pay.get('house') == 'rajya_sabha' else _safe_str(src.get('pdf_url'))
    is_debate=pay.get('content_type')=='debate'
    if is_debate:pdf_url=src.get('pdf_url') if debate_store.safe_url(src.get('pdf_url')) else None

    return EvidenceItem(
        score=score,
        chunk_id=str(pay.get("chunk_id") or p.id),
        question_id=_safe_str(pay.get("question_id")),
        lok_no=int(pay["lok_no"]) if pay.get("lok_no") is not None else None,
        session_no=int(pay["session_no"]) if pay.get("session_no") is not None else None,
        ques_no=pay.get("ques_no"),
        type=_safe_str(pay.get("type")),
        asked_by=_safe_str(pay.get("mp_names")),
        ministry=_safe_str(pay.get("ministry")),
        subject=_safe_str(pay.get("subject")),
        pdf_filename=_safe_str(src.get("pdf_filename")),
        pdf_url=pdf_url,
        chunk_index=int(src["chunk_index"]) if src.get("chunk_index") is not None else None,
        text=pay.get("text", ""),
        house=pay.get('house', 'lok_sabha'),
        date=pay.get('date'),
        source_url=src.get('source_url') or src.get('pdf_url'),
        document_url=pdf_url if is_debate else verified_document(pay) if pay.get('house')=='rajya_sabha' else None,
        content_type=pay.get('content_type','qa'),debate_category=pay.get('debate_category'),
        original_pages=pay.get('original_pages'),transcript_status=pay.get('transcript_status'),
    )


class Retriever:
    _query_lock = RLock()

    def __init__(
        self,
        host: str = QDRANT_HOST,
        port: int = QDRANT_PORT,
        collection: str = QDRANT_COLLECTION,
    ):
        self.client = QdrantClient(host=host, port=port, timeout=60)
        # Qdrant's local embedding accumulator is mutable per client. Concurrent
        # FastAPI requests must not change it while another query drains it.
        self._query_lock = RLock()
        self.model = EMBEDDING_MODEL
        self.collection = collection
        self.rs_collection = 'rajya_sabha_questions'
        try:
            manifest = json.loads((DATA_DIR/'rajya_sabha'/'manifest.json').read_text())
            self.rs_collection = manifest.get('collection') or self.rs_collection
        except (OSError, ValueError):
            pass

    def _record_collection(self, question_id):
        return self.rs_collection if question_id and question_id.startswith('RS_') else self.collection

    def _query_points(self, **kwargs):
        with self._query_lock:
            return self.client.query_points(**kwargs)

    def search(
        self,
        query: str,
        top_k: int = 10,
        lok: Optional[int] = None,
        session: Optional[int] = None,
        ministry: Optional[str] = None,
        mp_names: Optional[List[str]] = None,
        house: str = 'lok_sabha',
        content_type: str = 'qa',
        record_year: Optional[int] = None,
        record_dates: Optional[List[str]] = None,
    ) -> List[EvidenceItem]:
        if house not in ('lok_sabha', 'rajya_sabha', 'both'):
            raise ValueError('Unknown House')
        if content_type not in ('qa','debate','all'):raise ValueError('Unknown content type')
        query_filter = _build_filter(lok=lok, session=session, ministry=ministry, mp_names=mp_names, record_year=record_year, record_dates=record_dates)
        collections = [self.collection] if house == 'lok_sabha' else [self.rs_collection] if house == 'rajya_sabha' else [self.collection, self.rs_collection]
        if content_type=='debate':collections=[]
        found = [];ranked=[]
        for collection in collections:
            if collection == self.rs_collection and (lok is not None or not self.client.collection_exists(collection)):
                continue
            points = self._query_points(
            collection_name=collection,
            using='fast-' + self.model.split('/')[-1].lower() if collection == self.rs_collection else None,
            query=models.Document(text=query, model=self.model),
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
            search_params=models.SearchParams(hnsw_ef=256),
            ).points
            current=[_extract_evidence(p, score=float(p.score)) for p in points]
            found.extend(current);ranked.append(current)
        has_lexical=False
        if house != 'lok_sabha' and lok is None and content_type!='debate':
            historical=kaggle_store.search(query,limit=top_k,session=session,ministry=ministry,mp_names=mp_names,record_year=record_year,record_dates=record_dates)
            if historical:
                ranked.append([_extract_evidence(SimpleNamespace(id=r['question_id'],payload=kaggle_store.payload(r))) for r in historical])
                has_lexical=True
        if content_type!='qa':
            debates=debate_store.search(query,limit=top_k,session=session,ministry=ministry,mp_names=mp_names,house=house,lok=lok)
            if debates:
                ranked.append([_extract_evidence(SimpleNamespace(id=r['question_id'],payload=debate_store.payload(r))) for r in debates])
                has_lexical=True
        if has_lexical:return fuse_ranked(ranked,top_k)
        return sorted(found, key=lambda x: x.score, reverse=True)[:top_k]

    def build_context(self, items: List[EvidenceItem]) -> str:
        parts = ["EVIDENCE (verbatim chunks; cite as [E#]):"]
        for i, ev in enumerate(items, start=1):
            header = []
            header.append('Rajya Sabha' if ev.house == 'rajya_sabha' else 'Lok Sabha')
            if ev.date:
                header.append(f'Answer date: {ev.date}')
            if ev.lok_no is not None and ev.session_no is not None:
                header.append(f"Lok {ev.lok_no}, Session {ev.session_no}")
            if ev.ques_no is not None:
                header.append(f"Q{ev.ques_no}")
            if ev.ministry:
                header.append(f"Ministry: {ev.ministry}")
            if ev.asked_by:
                header.append(f"Asked by: {ev.asked_by}")
            if ev.subject:
                header.append(f"Subject: {ev.subject}")
            header.append(f"Score: {ev.score:.4f}")

            parts.append(f"\n[E{i}] " + " | ".join(header))
            parts.append(ev.text.strip() if ev.text else "")

        return "\n".join(parts).strip()

    def _fetch_leading_chunks(
        self,
        c: int,
        question_id: Optional[str] = None,
        lok_no: Optional[int] = None,
        session_no: Optional[int] = None,
        ques_no: Optional[int] = None,
        qtype: Optional[str] = None,
    ) -> List[EvidenceItem]:
        """Fetch the first C chunks (by chunk_index) for a specific question
        directly from Qdrant using metadata scroll, regardless of vector search.

        Prefers single-field question_id filter; falls back to 4-field composite.
        """
        if question_id and question_id.startswith(('RS_D_','LS_D_')):
            record=debate_store.get_record(question_id)
            if not record:return []
            data=debate_store.transcript(record)
            return [_extract_evidence(SimpleNamespace(id=question_id,payload=debate_store.payload(record,i,text,data['status'])))
                    for i,text in enumerate(islice(kaggle_store.split_text(data['text']),c))]
        if question_id and question_id.startswith('RS_K_'):
            record=kaggle_store.get_record(question_id)
            if not record:return []
            return [_extract_evidence(SimpleNamespace(id=question_id,payload=kaggle_store.payload(record,i,text)))
                    for i,text in enumerate(islice(kaggle_store.split_text(record['text']),c))]
        if question_id:
            must = [
                models.FieldCondition(key="question_id", match=models.MatchValue(value=question_id)),
                models.FieldCondition(
                    key="source.chunk_index",
                    range=models.Range(gte=0, lt=c),
                ),
            ]
        else:
            must = [
                models.FieldCondition(key="lok_no", match=models.MatchValue(value=lok_no)),
                models.FieldCondition(key="session_no", match=models.MatchValue(value=session_no)),
                models.FieldCondition(key="ques_no", match=models.MatchValue(value=ques_no)),
                models.FieldCondition(
                    key="source.chunk_index",
                    range=models.Range(gte=0, lt=c),
                ),
            ]
            if qtype:
                must.append(models.FieldCondition(key="type", match=models.MatchValue(value=qtype)))

        points, _ = self.client.scroll(
            collection_name=self._record_collection(question_id),
            scroll_filter=models.Filter(must=must),
            limit=c,
            with_payload=True,
        )

        items = [_extract_evidence(p) for p in points]
        items.sort(key=lambda c: c.chunk_index or 0)
        return items

    def _count_total_chunks(
        self,
        question_id: Optional[str] = None,
        lok_no: Optional[int] = None,
        session_no: Optional[int] = None,
        ques_no: Optional[int] = None,
        qtype: Optional[str] = None,
    ) -> int:
        """Count total chunks for a question in Qdrant."""
        if question_id and question_id.startswith(('RS_D_','LS_D_')):
            record=debate_store.get_record(question_id)
            if not record:return 0
            return sum(1 for _ in kaggle_store.split_text(debate_store.transcript(record)['text']))
        if question_id and question_id.startswith('RS_K_'):
            record=kaggle_store.get_record(question_id)
            return sum(1 for _ in kaggle_store.split_text(record['text'])) if record else 0
        if question_id:
            must = [
                models.FieldCondition(key="question_id", match=models.MatchValue(value=question_id)),
            ]
        else:
            must = [
                models.FieldCondition(key="lok_no", match=models.MatchValue(value=lok_no)),
                models.FieldCondition(key="session_no", match=models.MatchValue(value=session_no)),
                models.FieldCondition(key="ques_no", match=models.MatchValue(value=ques_no)),
            ]
            if qtype:
                must.append(models.FieldCondition(key="type", match=models.MatchValue(value=qtype)))

        result = self.client.count(
            collection_name=self._record_collection(question_id),
            count_filter=models.Filter(must=must),
            exact=True,
        )
        return result.count

    def group_evidence(
        self,
        items: List[EvidenceItem],
        top_n: Optional[int] = None,
        chunks_per_question: Optional[int] = None,
        prefer_matches: bool = False,
        required_years: Optional[List[int]] = None,
        answer_passages_only: bool = False,
    ) -> List[EvidenceGroup]:
        """Group flat evidence items by question_id (or 4-tuple fallback).

        Args:
            items: Flat list of evidence chunks from search.
            top_n: Keep only the top N questions (ranked by best chunk score).
                   None means keep all.
            chunks_per_question: For each question, fetch the first C chunks
                   (chunk_index 0..C-1) directly from Qdrant. None means use
                   whatever chunks were retrieved by vector search.
            prefer_matches: Preserve the strongest retrieved Q&A passage before
                   adding opening context within C. Used for AI answers.
        """
        groups: OrderedDict[str, List[EvidenceItem]] = OrderedDict()
        for item in items:
            key = item.question_id or f"{item.lok_no}_{item.session_no}_{item.ques_no}_{item.type}"
            groups.setdefault(key, []).append(item)

        result: List[EvidenceGroup] = []
        for idx, (key, chunk_list) in enumerate(groups.items(), start=1):
            best = max(chunk_list, key=lambda c: c.score)

            result.append(EvidenceGroup(
                group_index=idx,
                question_id=best.question_id,
                lok_no=best.lok_no,
                session_no=best.session_no,
                ques_no=best.ques_no,
                type=best.type,
                ministry=best.ministry,
                subject=best.subject,
                asked_by=best.asked_by,
                pdf_url=best.pdf_url,
                best_score=best.score,
                chunks=sorted(chunk_list, key=lambda c: c.chunk_index or 0),
                total_chunks_available=0,  # filled below if C is set
                house=best.house, date=best.date, source_url=best.source_url, retrieval_method=best.retrieval_method,document_url=best.document_url,
                content_type=best.content_type,debate_category=best.debate_category,original_pages=best.original_pages,transcript_status=best.transcript_status,
            ))

        # Sort by best_score descending, then trim to top N questions
        result.sort(key=lambda g: g.best_score, reverse=True)
        if top_n is not None:
            result = balanced_groups(result, required_years, top_n) if required_years else result[:top_n]

        # For each kept question, fetch the guaranteed first C chunks from Qdrant
        if chunks_per_question is not None:
            for g in result:
                if answer_passages_only and g.content_type == 'qa':
                    g.total_chunks_available = self._count_total_chunks(question_id=g.question_id,
                        lok_no=g.lok_no, session_no=g.session_no, ques_no=g.ques_no, qtype=g.type)
                    g.chunks = select_answer_chunks(g.chunks, [], chunks_per_question)
                    continue
                if g.content_type=='debate':
                    if g.transcript_status=='indexed_text':
                        from lok_sabha_rag.core import debate_fulltext
                        indexed=debate_fulltext.get(g.question_id)
                        g.total_chunks_available=indexed['chunk_count'] if indexed else len(g.chunks)
                        g.chunks=g.chunks[:chunks_per_question]
                        continue
                    row=debate_store.get_record(g.question_id)
                    if row:
                        data=debate_store.transcript(row);texts=list(kaggle_store.split_text(data['text']))
                        if row.get('source_pdf_url'):
                            g.pdf_url=row['source_pdf_url'];g.document_url=row['source_pdf_url']
                        g.total_chunks_available=len(texts);g.transcript_status=data['status']
                        g.chunks=[_extract_evidence(SimpleNamespace(id=g.question_id,payload=debate_store.payload(row,i,text,data['status']))) for i,text in enumerate(texts[:chunks_per_question])]
                    continue
                total = self._count_total_chunks(
                    question_id=g.question_id,
                    lok_no=g.lok_no,
                    session_no=g.session_no,
                    ques_no=g.ques_no,
                    qtype=g.type,
                )
                g.total_chunks_available = total
                leading = self._fetch_leading_chunks(
                    c=chunks_per_question,
                    question_id=g.question_id,
                    lok_no=g.lok_no,
                    session_no=g.session_no,
                    ques_no=g.ques_no,
                    qtype=g.type,
                )
                if prefer_matches:
                    g.chunks = select_answer_chunks(g.chunks, leading, chunks_per_question)
                elif leading:
                    g.chunks = leading
                    if g.content_type=='debate':g.transcript_status=leading[0].transcript_status
                # If fetch failed, keep original chunks as fallback

        # Re-assign group_index after trimming so citations are 1..N
        for i, g in enumerate(result, start=1):
            g.group_index = i

        return result

    def build_context_grouped(self, groups: List[EvidenceGroup]) -> str:
        """Build LLM context string from grouped evidence. Uses [Q#] citation labels."""
        parts = ["EVIDENCE (grouped by parliamentary record; cite as [Q#]):"]

        for g in groups:
            header = []
            header.append(f'Content type: {g.content_type}')
            if g.content_type=='debate':
                header.append(f'Category: {g.debate_category}; original pages: {g.original_pages}; transcript status: {g.transcript_status}')
            header.append('Rajya Sabha' if g.house == 'rajya_sabha' else 'Lok Sabha')
            if g.date:
                header.append(f'Answer date: {g.date}')
            if g.source_url:
                header.append(f'Source: {g.source_url}')
            if g.pdf_url and g.pdf_url != g.source_url:
                header.append(f'Official PDF: {g.pdf_url}')
            if g.house == 'rajya_sabha' and g.session_no:
                header.append(f'Session {g.session_no}')
                header.append(f'Dataset record: {g.question_id}')
            if g.lok_no is not None and g.session_no is not None:
                header.append(f"Lok {g.lok_no}, Session {g.session_no}")
            if g.ques_no is not None:
                header.append(f"Q{g.ques_no}")
            if g.ministry:
                header.append(f"Ministry: {g.ministry}")
            if g.asked_by:
                header.append(f"{'Participants listed' if g.content_type=='debate' else 'Asked by'}: {g.asked_by}")
            if g.subject:
                header.append(f"Subject: {g.subject}")

            parts.append(f"\n[Q{g.group_index}] " + " | ".join(header))

            for chunk in g.chunks:
                text = chunk.text.strip() if chunk.text else ""
                if text:
                    parts.append(text)

            # Note about trailing chunks that were trimmed
            trimmed = g.total_chunks_available - len(g.chunks)
            if trimmed > 0:
                parts.append(
                    f"\n[NOTE: This question has {trimmed} more chunk(s) with "
                    f"additional details (annexures, tables, etc.) not shown here. "
                    f"Refer to the {'source PDF' if g.pdf_url else 'dataset source record'} for complete information.]"
                )

        return "\n".join(parts).strip()


def to_dict_list(items: List[EvidenceItem]) -> List[Dict[str, Any]]:
    return [asdict(e) for e in items]
