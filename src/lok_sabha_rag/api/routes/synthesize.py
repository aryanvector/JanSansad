"""Synthesize endpoint - LLM-powered answer generation."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from lok_sabha_rag.core.retriever import Retriever, EvidenceItem, EvidenceGroup
from lok_sabha_rag.core.stats import get_mp_stats, format_stats_for_llm, get_ministry_stats, format_ministry_stats_for_llm

_LOG_CHUNKS = os.environ.get("RAG_LOG_CHUNKS", "").strip() == "1"
from lok_sabha_rag.core.synthesizer import Synthesizer, extract_citations, validate_citations
from lok_sabha_rag.core.ai_provider import GenerationError
from lok_sabha_rag.core.temporal_retrieval import retrieve_comparison, period_coverage, coverage_context
from lok_sabha_rag.core.scoped_retrieval import retrieve_scoped, scope_context
from lok_sabha_rag.core.answer_checks import generate_checked
from lok_sabha_rag.core.relevance import relevant_items, NO_RESULTS
from lok_sabha_rag.api.schemas import (
    SynthesizeRequest,
    SynthesizeResponse,
    EvidenceGroupResponse,
    MpStatsResponse,
    MinistryStatsResponse,
    ChunkDetail,
)

router = APIRouter()

retriever = Retriever()
synthesizer = Synthesizer()


def _truncate(text: str, max_len: int = 200) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _log_retrieval(
    query: str,
    items: list[EvidenceItem],
    groups: list[EvidenceGroup],
    req: SynthesizeRequest,
) -> None:
    """Pretty-print retrieved chunks and final grouped questions to terminal."""
    filter_str = f"  mp_names={req.mp_names}" if req.mp_names else ""
    print(f"\n{'━'*70}")
    print(f"  SYNTHESIZE | query={query!r}")
    print(f"  M={req.top_k}  N={req.top_n}  C={req.chunks_per_question}{filter_str}")
    print(f"{'━'*70}")

    # Log raw retrieved chunks
    seen: set[tuple] = set()
    for i, item in enumerate(items, 1):
        qkey = (item.lok_no, item.session_no, item.type, item.ques_no)
        new_q = qkey not in seen
        seen.add(qkey)
        marker = "★" if new_q else " "
        subject = (item.subject or "?")[:55]
        asked = item.asked_by or "?"
        print(f"  {marker} [{i:>2}] Q{item.ques_no or '?'} chunk={item.chunk_index}  score={item.score:.3f}  {subject}")
        if new_q:
            print(f"         Asked by: {asked}")
    print(f"{'─'*70}")
    print(f"  Retrieved {len(items)} chunks from {len(seen)} unique questions")

    # Log grouped + trimmed questions sent to LLM
    print(f"\n  → Grouped into {len(groups)} questions for LLM:")
    for g in groups:
        subject = (g.subject or "?")[:55]
        asked = g.asked_by or "?"
        trimmed = g.total_chunks_available - len(g.chunks)
        trail = f"  (+{trimmed} trailing)" if trimmed > 0 else ""
        print(f"    [Q{g.group_index}] Q{g.ques_no} | {len(g.chunks)} chunks{trail} | score={g.best_score:.3f}")
        print(f"         Subject: {subject}")
        print(f"         Asked by: {asked}")
    print(f"{'━'*70}\n")


@router.post("/synthesize", response_model=SynthesizeResponse)
def synthesize(req: SynthesizeRequest) -> SynthesizeResponse:
    filters = dict(lok=req.lok, session=req.session, ministry=req.ministry,
        mp_names=req.mp_names, house=req.house, content_type=req.content_type)
    scoped = retrieve_scoped(retriever, req.query, req.top_k, req.top_n,
        req.chunks_per_question, **filters)
    source_scope = None
    if scoped is not None:
        items, source_scope = scoped
        years = []
    else:
        items, years = retrieve_comparison(retriever,
        query=req.query,
        top_k=req.top_k,
        lok=req.lok,
        session=req.session,
        ministry=req.ministry,
        mp_names=req.mp_names,
        house=req.house,
        content_type=req.content_type,
        )

    items = relevant_items(req.query, items)
    if not items:
        raise HTTPException(
            status_code=404,
            detail=(f"No matching indexed evidence was retrieved for the requested comparison topics, answer dates and Houses with the selected filters. Missing sides: {[(s['date'], s['house'], s['topic']) for s in source_scope['comparison_slots'] if s['status'] != 'matched']}. This does not establish that the requested records do not exist."
                    if source_scope and source_scope.get('comparison_slots') else
                    f"No matching indexed passages found for the requested answer dates {source_scope['requested_dates']} and named anchors {source_scope['anchors']} with the selected filters. This does not establish that the date or place is wrong."
                    if source_scope else f"No matching Q&A evidence found for the requested record years {', '.join(map(str, years))}. Try a different period or remove filters."
                    if years else NO_RESULTS),
        )

    # Fetch stats from metadata DB when a filter is active
    mp_stats = None
    ministry_stats = None
    stats_text = ""
    if req.house == 'lok_sabha' and req.content_type=='qa' and req.mp_names and len(req.mp_names) == 1:
        mp_stats = get_mp_stats(req.mp_names[0], top_q=req.top_q or 10)
        if mp_stats:
            stats_text = format_stats_for_llm(mp_stats)
    elif req.house == 'lok_sabha' and req.content_type=='qa' and req.ministry:
        ministry_stats = get_ministry_stats(req.ministry, top_q=req.top_q or 10)
        if ministry_stats:
            stats_text = format_ministry_stats_for_llm(ministry_stats)

    # Group by parliamentary question, trim to top N questions with C chunks each
    groups = retriever.group_evidence(
        items,
        top_n=req.top_n,
        chunks_per_question=req.chunks_per_question,
        prefer_matches=True,
        required_years=years,
        answer_passages_only=source_scope is not None,
    )

    if _LOG_CHUNKS:
        _log_retrieval(req.query, items, groups, req)
        if mp_stats:
            print(f"  MP Stats: {mp_stats.mp_name} — {mp_stats.total_questions} total questions, showing {len(mp_stats.recent_questions)} recent")

    # Build grouped context for LLM (no scores, [Q#] labels)
    evidence_context = retriever.build_context_grouped(groups)
    coverage = period_coverage(groups, years)
    scope = coverage_context(coverage)
    if scope:
        evidence_context = scope + '\n\n' + evidence_context
    if source_scope:
        evidence_context = scope_context(source_scope) + '\n\n' + evidence_context

    # Compose full context: stats (if available) + evidence
    if stats_text:
        context = stats_text + "\n\n" + evidence_context
    else:
        context = evidence_context

    try:answer, answer_checks = generate_checked(synthesizer, req.query, context, groups)
    except GenerationError as error:raise HTTPException(error.status_code,str(error)) from None
    if validate_citations(answer,len(groups)):
        raise HTTPException(502,'The AI answer referenced unavailable evidence and was withheld. Try again or use document search.')
    citations = extract_citations(answer, max_n=len(groups))

    evidence_groups = [
        EvidenceGroupResponse(
            group_index=g.group_index,
            house=g.house, date=g.date, source_url=g.source_url,
            retrieval_method=g.retrieval_method,
            document_url=g.document_url,
            content_type=g.content_type,debate_category=g.debate_category,original_pages=g.original_pages,transcript_status=g.transcript_status,
            question_id=g.question_id,
            lok_no=g.lok_no,
            session_no=g.session_no,
            ques_no=g.ques_no,
            type=g.type,
            ministry=g.ministry,
            subject=g.subject,
            asked_by=g.asked_by,
            pdf_url=g.pdf_url,
            best_score=g.best_score,
            total_chunks_available=g.total_chunks_available,
            chunks=[
                ChunkDetail(
                    chunk_index=chunk.chunk_index,
                    score=chunk.score,
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    text_preview=_truncate(chunk.text),
                )
                for chunk in g.chunks
            ],
        )
        for g in groups
    ]

    # Build stats responses for frontend display
    mp_stats_response = None
    if mp_stats:
        mp_stats_response = MpStatsResponse(
            mp_name=mp_stats.mp_name,
            total_questions=mp_stats.total_questions,
            by_lok=mp_stats.by_lok,
            by_session=mp_stats.by_session,
            by_type=mp_stats.by_type,
            top_ministries=[
                {"ministry": m, "count": c} for m, c in mp_stats.by_ministry
            ],
            recent_questions=[
                {
                    "lok_no": q.lok_no,
                    "session_no": q.session_no,
                    "ques_no": q.ques_no,
                    "type": q.type,
                    "date": q.date,
                    "ministry": q.ministry,
                    "subject": q.subject,
                }
                for q in mp_stats.recent_questions
            ],
        )

    ministry_stats_response = None
    if ministry_stats:
        ministry_stats_response = MinistryStatsResponse(
            ministry=ministry_stats.ministry,
            total_questions=ministry_stats.total_questions,
            by_lok=ministry_stats.by_lok,
            by_session=ministry_stats.by_session,
            by_type=ministry_stats.by_type,
            top_mps=[
                {"mp_name": m, "count": c} for m, c in ministry_stats.top_mps
            ],
            recent_questions=[
                {
                    "lok_no": q.lok_no,
                    "session_no": q.session_no,
                    "ques_no": q.ques_no,
                    "type": q.type,
                    "date": q.date,
                    "ministry": q.ministry,
                    "subject": q.subject,
                }
                for q in ministry_stats.recent_questions
            ],
        )

    return SynthesizeResponse(
        query=req.query,
        answer=answer,
        citations_used=citations,
        evidence_groups=evidence_groups,
        total_chunks=len(items),
        mp_stats=mp_stats_response,
        ministry_stats=ministry_stats_response,
        period_coverage=coverage,
        source_scope=source_scope,
        answer_checks=answer_checks,
    )
