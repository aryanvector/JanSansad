"""Bounded lexical topic checks for explicit answer-date comparisons.

Conservative English clause heuristics, not semantic relevance certification.
Ambiguous/unsupported wording retains the existing retrieval path.
"""
from dataclasses import replace
import re
from .passage_selection import complementary_order

HOUSE = re.compile(r'\b(lok\s+sabha|rajya\s+sabha)\b', re.I)
META = set('compare comparison contrast versus vs between statements statement status measures measure metric metrics stocks stock described describe supports support using use only respective respectively keep separate separately information give reported report answer answers reply replies question questions dated date on of in the and with from to for what which how did does was were is are a an as at by regarding according parliamentary parliament lok rajya sabha'.split())


def words(text):
    return re.findall(r'[A-Za-z][A-Za-z0-9]*', text)


def normal(word):
    value = word.casefold()
    return value[:-1] if value.endswith('s') and len(value) > 4 else value


def plan_slots(query):
    from .scoped_retrieval import date_spans, requested_answer_dates, STOP
    if not re.search(r'\b(compare|contrast|comparison|versus|between)\b', query, re.I):
        return None
    allowed = requested_answer_dates(query)
    spans = [s for s in date_spans(query) if s[2] in allowed]
    if not 2 <= len(spans) <= 4:
        return None
    slots = []
    global_houses = {re.sub(r'\s+', '_', h.casefold()) for h in HOUSE.findall(query)}
    previous_end = 0
    inherited = None
    # Each side ends at its record date. Topic following a date is unsupported
    # here rather than silently assigned to the wrong side.
    for start, end, value in spans:
        clause = query[previous_end:start]
        previous_end = end
        houses = HOUSE.findall(clause)
        if len(set(h.casefold() for h in houses)) > 1:
            return None
        house = re.sub(r'\s+', '_', houses[-1].casefold()) if houses else None
        if house is None and len(global_houses) == 1:
            house = next(iter(global_houses))
        text = HOUSE.sub(' ', clause)
        terms = [w for w in words(text) if w.casefold() not in META | STOP]
        if terms:
            # Capitalised names and acronyms supply a stricter identity gate.
            identities = [w for w in terms if w[0].isupper() and len(w) > 1]
            topic = ' '.join(terms)
            inherited = (topic, identities)
        elif inherited:
            topic, identities = inherited
        else:
            return None
        slots.append({'date': value, 'house': house, 'topic': topic,
                      'identities': identities, 'terms': sorted({normal(w) for w in words(topic)})})
    return slots


def relevant(text, slot):
    present = {normal(w) for w in words(text)}
    # Slash-separated acronyms (e.g. two institutions) are alternatives within
    # one side, while explicit place/name tokens must all occur.
    acronyms = [normal(w) for w in slot['identities'] if w.isupper()]
    names = [normal(w) for w in slot['identities'] if not w.isupper()]
    if acronyms and not any(w in present for w in acronyms):
        return False
    if names and not all(w in present for w in names):
        return False
    terms = set(slot['terms'])
    return len(terms & present) >= min(2, len(terms))


def retrieve_slots(retriever, query, top_k, top_n, chunks_per_question, **filters):
    slots = plan_slots(query)
    if slots is None:
        return None
    rows, cache = [], {}
    for index, slot in enumerate(slots):
        quota = top_k // len(slots) + (index < top_k % len(slots))
        if not quota:
            continue
        selected_house = filters.get('house')
        if slot['house'] and selected_house not in (None, 'both', slot['house']):
            continue  # Never relax a conflicting user filter.
        kwargs = {**filters, 'record_dates': [slot['date']]}
        if slot['house']:
            kwargs['house'] = slot['house']
        candidates = retriever.search(query=slot['topic'], top_k=quota, **kwargs)
        for item in candidates:
            if item.content_type != 'qa' or item.date != slot['date']:
                continue
            if kwargs.get('house') not in (None, 'both', item.house):
                continue
            key = (item.house, item.question_id or item.chunk_id)
            if key not in cache:
                cache[key] = retriever._fetch_leading_chunks(c=64, question_id=item.question_id,
                    lok_no=item.lok_no, session_no=item.session_no, ques_no=item.ques_no, qtype=item.type) or [item]
            chunks = cache[key]
            full = (item.subject or '') + '\n' + '\n'.join(c.text for c in chunks)
            if not relevant(full, slot):
                continue
            terms = set(slot['terms'])
            ranked = sorted(chunks, key=lambda c: (-len(terms & {normal(w) for w in words(c.text)}), c.chunk_index or 0))
            ranked = complementary_order(ranked, slot['topic'])
            if not any(r['key'] == key and r['slot'] == index for r in rows):
                rows.append({'key': key, 'slot': index, 'chunks': ranked, 'score': item.score})
    # Reserve one source for each slot before filling remaining source budget.
    selected, seen = [], set()
    limit = min(top_n or top_k, top_k)
    for index in range(len(slots)):
        choices = sorted((r for r in rows if r['slot'] == index), key=lambda r: -r['score'])
        row = next((r for r in choices if r['key'] not in seen), None)
        if row and len(selected) < limit:
            selected.append(row); seen.add(row['key'])
    for row in sorted(rows, key=lambda r: -r['score']):
        if len(selected) >= limit:
            break
        if row['key'] not in seen:
            selected.append(row); seen.add(row['key'])
    items = []
    for passage in range(chunks_per_question or 2):
        for rank, row in enumerate(selected):
            if passage < len(row['chunks']) and len(items) < top_k:
                items.append(replace(row['chunks'][passage], score=float(len(selected)-rank) + .01/(passage+1),
                                     retrieval_method='comparison_slot_passages'))
    # Only count sources actually represented in the final passage budget.
    represented = {(i.house, i.question_id or i.chunk_id) for i in items}
    for index, slot in enumerate(slots):
        slot['selected_record_ids'] = sorted({r['key'][1] for r in rows if r['slot'] == index and r['key'] in represented})
        slot['status'] = 'matched' if slot['selected_record_ids'] else 'missing_matching_evidence'
    dates = list(dict.fromkeys(s['date'] for s in slots))
    return items, {'planner': 'explicit_comparison_slots_v2', 'requested_dates': dates,
        'anchors': [], 'schemes': [], 'comparison_slots': slots,
        'missing_dates': [d for d in dates if not any(s['date']==d and s['selected_record_ids'] for s in slots)],
        'missing_anchors': [], 'candidate_records':len(cache), 'selected_records':len(represented),
        'note':'Lexical clause/topic matching is heuristic. A matching record does not establish factual support for every requested claim.'}
