"""Conservative answer-date and named-anchor retrieval for parliamentary Q&A.

No inferred constituency IDs or external biographies. Capitalised anchors are
heuristics, not a complete geographic named-entity recogniser. Source matching
does not certify the factual correctness of a generated claim.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from .passage_selection import complementary_order
import calendar
import re

MONTHS = {name.casefold(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.casefold(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTHS['sept'] = 9
MONTH_PATTERN = '|'.join(sorted(MONTHS, key=len, reverse=True))
DATE_PATTERNS = [
    re.compile(r'\b(?P<year>20\d{2}|19[5-9]\d)-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b'),
    re.compile(r'\b(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>20\d{2}|19[5-9]\d)\b'),
    re.compile(rf'\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{MONTH_PATTERN})\.?\s*,?\s*(?P<year>20\d{{2}}|19[5-9]\d)\b', re.I),
    re.compile(rf'\b(?P<month>{MONTH_PATTERN})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(?P<year>20\d{{2}}|19[5-9]\d)\b', re.I),
]
SCHEMES = {
    'PM SHRI': ('pmshri', 'pradhanmantrischoolsforrisingindia'),
    'PM POSHAN': ('pmposhan', 'pradhanmantriposhanshaktinirman', 'middaymeal'),
    'PM-ABHIM': ('pmabhim', 'ayushmanbharathealthinfrastructuremission'),
    'Kavach': ('kavach',),
    'Samagra Shiksha': ('samagrashiksha',),
    'PM-JAY': ('pmjay', 'pradhanmantrijanarogyayojana'),
    'NHM': ('nationalhealthmission',),
}
STOP = set('what which when where how why the a an of in on to and or is are was were has have for from about me tell please give details regarding according answer answers answered reply replies parliamentary parliament lok sabha rajya question questions no number dated date reported reports report provided records record scheme total does do did can could would should under as at with its that this these those by using keep separately specific specifically explain whether national nationwide country across compare comparison same other their your crore lakh rs fiscal fy financial year years list show identify state define evaluate clarify describe provide summarize find check march january february april may june july august september october november december'.split())
CAP_STOP = STOP | set('government ministry minister state states ut uts centre central indian india railway railways education health family welfare schools school medical colleges college aiims ini inis mbbs pg pab css approved approval actual expenditure outlay selected centre-state north south east west eastern special category neps nep version automatic train protection i viii ii iii iv v vi vii'.split())


def compact(text):
    return re.sub(r'[^a-z0-9]', '', text.casefold())


def date_spans(query):
    found = []
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(query):
            if any(match.start() < end and match.end() > start for start, end, _ in found):
                continue
            raw = match.group('month').casefold()
            month = MONTHS.get(raw) if raw in MONTHS else int(raw)
            try:
                value = date(int(match.group('year')), month, int(match.group('day'))).isoformat()
            except ValueError:
                continue
            found.append((match.start(), match.end(), value))
    return sorted(found)


def requested_answer_dates(query):
    result = []
    for start, end, value in date_spans(query):
        before = query[max(0, start-90):start]
        after = query[end:end+90]
        # An as-of/through date describes the observation, not the record date.
        if re.search(r'\b(as\s+of|up\s+to|upto|through|until|by)\s*$', before, re.I):
            continue
        if re.search(r'\b(advisory|notification|circular|adoption|launch)\s+(?:dated?|on|of)?\s*$', before, re.I):
            continue
        if re.search(r'\b(answer\w*|repl(?:y|ies)|parliamentary|records?|question)\b', before+' '+after, re.I):
            if value not in result:
                result.append(value)
    return result[:4]


def named_anchors(query, schemes):
    text = query
    for start, end, _ in reversed(date_spans(query)):
        text = text[:start] + ' ' + text[end:]
    for name in schemes:
        text = re.sub(re.escape(name).replace(r'\ ', r'[\s-]*'), ' ', text, flags=re.I)
    anchors = []
    for match in re.finditer(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text):
        words = [w for w in match.group().split() if w.casefold() not in CAP_STOP and w.casefold() not in MONTHS]
        if words:
            value = ' '.join(words)
            if value not in anchors:
                anchors.append(value)
    # Lowercase constituency/district names are supported when explicitly tagged.
    for match in re.finditer(r'\b([a-z]+)\s+(?:lok\s+sabha\s+)?(?:constituency|district)\b', text, re.I):
        value = match.group(1)
        if value.casefold() not in CAP_STOP and not any(value.casefold() == a.casefold() for a in anchors):
            anchors.append(value)
    return anchors[:4]


def query_plan(query):
    key = compact(query)
    schemes = [name for name, aliases in SCHEMES.items() if any(alias in key for alias in aliases)]
    dates = requested_answer_dates(query)
    anchors = named_anchors(query, schemes)
    # Do not activate anchor-only heuristics for arbitrary person/topic questions.
    if not dates and not (schemes and anchors):
        return None
    text = query
    for start, end, _ in reversed(date_spans(query)):
        text = text[:start]+' '+text[end:]
    tokens = re.findall(r'[A-Za-z][A-Za-z0-9-]*|\d+(?:[.,]\d+)*', text)
    cleaned = ' '.join(t for t in tokens if t.casefold() not in STOP and t.casefold() not in MONTHS)
    return {'requested_dates':dates,'schemes':schemes,'anchors':anchors,
            'topic_query':cleaned or query,'record_scan_cap':64}


def tokens(text):
    return {t.replace(',', '').casefold() for t in re.findall(r'[A-Za-z][A-Za-z0-9]*|\d+(?:[.,]\d+)*', text)
            if t.casefold() not in STOP and len(t) > 1}


def has_anchor(text, anchor):
    pattern = r'\s+'.join(re.escape(word) for word in anchor.split())
    return bool(re.search(r'(?<!\w)'+pattern+r'(?!\w)', text, re.I))


def retrieve_scoped(retriever, query, top_k, top_n, chunks_per_question, **filters):
    if filters.get('content_type', 'qa') != 'qa':
        return None
    from .comparison_slots import retrieve_slots
    comparison = retrieve_slots(retriever, query, top_k, top_n, chunks_per_question, **filters)
    if comparison is not None:
        return comparison
    plan = query_plan(query)
    if plan is None:
        return None
    dates, anchors = plan['requested_dates'], plan['anchors']
    slots = [('date', d) for d in dates] or [('anchor', a) for a in anchors]
    if not slots:
        return None
    candidates = {}
    for i, (kind, value) in enumerate(slots):
        quota = top_k // len(slots) + (i < top_k % len(slots))
        if not quota:
            continue
        topic = plan['topic_query']
        if kind == 'anchor':
            for other in anchors:
                if other != value:
                    topic = re.sub(re.escape(other), ' ', topic, flags=re.I)
            topic = value+' '+topic
        kwargs = dict(filters)
        if kind == 'date':
            kwargs['record_dates'] = [value]
        for item in retriever.search(query=topic, top_k=quota, **kwargs):
            if item.content_type != 'qa' or (dates and item.date not in dates):
                continue
            key = (item.house, item.question_id or item.chunk_id)
            candidates.setdefault(key, []).append(item)

    terms = tokens(plan['topic_query'])
    numeric_request = bool(re.search(r'\b(how many|how much|outlay|share|budget|amount|count|length|coverage|kilometres?|kilometers?|expenditure|figures?)\b', query, re.I))
    eligible, inspected = [], set()

    def inspect_new_candidates():
        for key, matched in candidates.items():
            if key in inspected:
                continue
            inspected.add(key)
            best = max(matched, key=lambda x:x.score)
            chunks = retriever._fetch_leading_chunks(c=plan['record_scan_cap'], question_id=best.question_id,
                lok_no=best.lok_no, session_no=best.session_no, ques_no=best.ques_no, qtype=best.type) or matched
            full = '\n'.join(c.text for c in chunks)
            joined = compact(full)
            if plan['schemes'] and not all(any(alias in joined for alias in SCHEMES[s]) for s in plan['schemes']):
                continue
            hits = [a for a in anchors if has_anchor(full, a)]
            if anchors and not hits:
                continue
            def passage_score(chunk):
                present = tokens(chunk.text)
                score = sum(4 if any(c.isdigit() for c in term) else 1 for term in terms & present)
                # Structured numeric answers often have very short tables while
                # the introduction repeats many broad query terms. Reward a
                # matching table, not an arbitrary table in the same record.
                if numeric_request and '|' in chunk.text and re.search(r'\|[^\n]*\d[^\n]*\|', chunk.text) and len(terms & present) >= 2:
                    score += 10
                return score
            ranked = sorted(chunks, key=lambda c:(-passage_score(c), c.chunk_index or 0))
            ranked = complementary_order(ranked, query)
            # Carry only an explicit unit heading immediately before a table.
            # This is source text from the same record, not a guessed unit.
            by_index = {c.chunk_index: c for c in chunks if c.chunk_index is not None}
            enriched = []
            for chunk in ranked:
                previous = by_index.get((chunk.chunk_index or 0)-1)
                if '|' in chunk.text and previous:
                    lines = [line.strip() for line in previous.text.splitlines() if line.strip()]
                    unit = lines[-1] if lines else ''
                    if len(unit) <= 100 and re.fullmatch(r'\(?\s*(?:₹|rs\.?|rupees|amounts?|figures?)?\s*in\s+(?:crores?|lakhs?|millions?|billions?|thousands?|rupees)(?:\s*\))?', unit, re.I):
                        chunk = replace(chunk, text='Source unit heading from immediately preceding passage: '+unit+'\n\n'+chunk.text)
                enriched.append(chunk)
            ranked = enriched
            primary = (best.subject or '')+' '+full[:1500]
            score = passage_score(ranked[0]) + 4*sum(has_anchor(primary,a) for a in hits)
            eligible.append({'key':key,'date':best.date,'anchors':hits,'score':score,'chunks':ranked})

    inspect_new_candidates()
    # One bounded rescue pass when descriptive words crowd out a programme or
    # place. The original question still ranks passages and reaches synthesis.
    # Never drop source dates, House, ministry or MP filters to get a match.
    missing_slots = [(kind, value) for kind, value in slots if not any(
        row['date'] == value if kind == 'date' else value in row['anchors'] for row in eligible)]
    rescue_queries = []
    if missing_slots and plan['schemes']:
        for i, (kind, value) in enumerate(missing_slots):
            quota = top_k // len(missing_slots) + (i < top_k % len(missing_slots))
            if not quota:
                continue
            names = anchors if kind == 'date' else [value]
            topic = ' '.join(names + plan['schemes'])
            if topic.casefold().strip() == plan['topic_query'].casefold().strip():
                continue
            kwargs = dict(filters)
            if kind == 'date':
                kwargs['record_dates'] = [value]
            rescue_queries.append(topic)
            for item in retriever.search(query=topic, top_k=quota, **kwargs):
                if item.content_type != 'qa' or (dates and item.date not in dates):
                    continue
                key = (item.house, item.question_id or item.chunk_id)
                candidates.setdefault(key, []).append(item)
        inspect_new_candidates()
    eligible.sort(key=lambda d:(-d['score'],d['key']))
    # Reserve sources across requested dates/entities before filling remaining N.
    selected, seen = [], set()
    groups = [('date', d) for d in dates] or [('anchor', a) for a in anchors]
    limit = min(top_n or top_k, top_k)
    for kind, value in groups:
        row = next((d for d in eligible if (d['date']==value if kind=='date' else value in d['anchors']) and d['key'] not in seen), None)
        if row and len(selected)<limit:
            selected.append(row);seen.add(row['key'])
    for row in eligible:
        if len(selected)>=limit:break
        if row['key'] not in seen:selected.append(row);seen.add(row['key'])
    # Each source gets a first passage before any source gets its second.
    items=[]
    c_limit=chunks_per_question or 2
    for index in range(c_limit):
        for rank, row in enumerate(selected):
            if index<len(row['chunks']) and len(items)<top_k:
                chunk=row['chunks'][index]
                items.append(replace(chunk,score=float(len(selected)-rank)+(c_limit-index)/100,
                    retrieval_method='date_anchor_passages'))
    plan.update(candidate_records=len(candidates),eligible_records=len(eligible),
        rescue_queries=rescue_queries, retrieval_passes=2 if rescue_queries else 1,
        selected_records=len(selected),missing_dates=[d for d in dates if not any(r['date']==d for r in selected)],
        missing_anchors=[a for a in anchors if not any(a in r['anchors'] for r in selected)],
        note='Answer dates are source constraints, not observation dates. Named anchors are heuristic text matches, not verified geographic identities. Only bounded indexed passages were scanned.')
    return items, plan


def scope_context(plan):
    if not plan:return ''
    slots = plan.get('comparison_slots', [])
    slot_note = ''
    if slots:
        slot_note = 'Requested comparison sides (date / House / topic / status / source IDs):\n' + '\n'.join(
            f'- {s["date"]} / {s["house"] or "selected House filter"} / {s["topic"]} / {s["status"]} / {s["selected_record_ids"]}' for s in slots) + '\n'
        slot_note += ('A same-date reply on another topic is NOT the requested reply. For any missing side, state that matching evidence was not retrieved; do not claim the requested source says nothing or does not exist. '
                      'A partial answer is not a complete comparison. Do not calculate changes across missing or incompatible measures.\n')
    return ('=== REQUESTED SOURCE SCOPE ===\n'
        f'Explicit answer dates: {plan["requested_dates"]}. Named text anchors: {plan["anchors"]}. Schemes/topics: {plan["schemes"]}.\n'
        f'Missing requested dates in selected records: {plan["missing_dates"]}. Missing named anchors: {plan["missing_anchors"]}.\n'
        + slot_note +
        'Answer only from the supplied matching passages. Do not substitute another date, place or scheme. '
        'If a requested detail is missing, say the retrieved evidence does not establish it. Never call the user date wrong merely because a different source was found. '
        'Preserve more than/about, numbers, units, approved versus functional status, observation dates and record dates. '
        'An anchor text match does not prove that every figure in a national table describes that place.\n'
        '=== END REQUESTED SOURCE SCOPE ===')
