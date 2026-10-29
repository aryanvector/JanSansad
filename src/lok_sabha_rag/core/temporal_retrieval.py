"""Bounded retrieval for explicit calendar-year comparisons of Q&A records.

Record date is a retrieval constraint, not the observation period of a statistic.
No LLM query planner, new embeddings, or inferred date facts are involved.
"""
from __future__ import annotations

from collections import deque
from datetime import date, timedelta
import re


_YEAR = re.compile(r"(?<!\d)(19[5-9]\d|20\d\d|2100)(?!\d)")
_COMPARISON = re.compile(r"\b(compare|comparison|versus|vs|between|difference|changes?|changed|progress|growth|tulna|badlav)\b|तुलना|बनाम|अंतर", re.I)
_RANGE = re.compile(r"\b(19[5-9]\d|20\d\d|2100)\s*(?:[-–—]|to|through|se|से)\s*(19[5-9]\d|20\d\d|2100)\b", re.I)


def comparison_years(query: str) -> list[int]:
    """Conservative activation: explicit comparison cue and 2–4 full years.

    Financial-year shorthand is deliberately not expanded into calendar years.
    Larger ranges and unsupported wording use the normal retrieval path.
    """
    if not _COMPARISON.search(query):
        return []
    # Milestone years can be described in much later parliamentary records.
    # Do not treat them as publication-year constraints unless explicitly asked.
    if re.search(r'\b(trials?|adopt\w*|introduc\w*|launch\w*|invent\w*|approv\w*)\b', query, re.I) and not re.search(r'\b(parliamentary|records?|responses?|reports?|answers?)\b', query, re.I):
        return []
    if re.search(r"\b(?:FY|fiscal|financial)\b|वित्त", query, re.I):
        return []
    if re.search(r"(?<!\d)(?:19[5-9]\d|20\d\d)\s*[-–/]\s*\d{2}(?!\d)", query):
        return []
    years = sorted({int(y) for y in _YEAR.findall(query)})
    for start, end in _RANGE.findall(query):
        start, end = int(start), int(end)
        if end < start or end - start > 3:
            return []
        years = sorted(set(years) | set(range(start, end + 1)))
    return years if 2 <= len(years) <= 4 else []


def dates_in_year(year: int) -> list[str]:
    """Exact ISO-date matches work with the existing date-only payloads."""
    if not 1950 <= year <= 2100:
        raise ValueError("Unsupported calendar year")
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days)]


def comparison_search_query(query: str) -> str:
    """Keep the topic; record-year constraints already supply the date scope.

    Output-format and missing-evidence instructions should not dominate dense
    similarity. The original question is still supplied unchanged to Gemini.
    """
    core = re.split(r'[.!?]\s+(?:if|give|please|only|cite|do not|state|use)\b', query, maxsplit=1, flags=re.I)[0]
    core = _YEAR.sub(' ', core)
    core = re.sub(r'\b(compare|comparison|versus|vs|between|reported|parliamentary|answers?|responses?|records?|and|in|for|the|of|from|to)\b', ' ', core, flags=re.I)
    core = re.sub(r'\s+', ' ', core).strip(' .,:;?!-–')
    return core if len(re.findall(r'\w+', core)) >= 2 else query


def balanced_groups(groups, years: list[int], limit: int):
    """Round-robin by requested year so trimming N cannot hide a whole period."""
    buckets = [deque(g for g in groups if str(g.date or '').startswith(f'{year}-')) for year in years]
    selected = []
    while len(selected) < limit and any(buckets):
        for bucket in buckets:
            if bucket and len(selected) < limit:
                selected.append(bucket.popleft())
    return selected


def retrieve_comparison(retriever, query: str, top_k: int, **filters):
    years = comparison_years(query) if filters.get('content_type', 'qa') == 'qa' else []
    if not years:
        return retriever.search(query=query, top_k=top_k, **filters), []
    # Total requested returned chunks remains M across all year subqueries.
    quotas = [top_k // len(years) + (i < top_k % len(years)) for i in range(len(years))]
    buckets = []
    topic_query = comparison_search_query(query)
    for year, quota in zip(years, quotas):
        items = retriever.search(query=topic_query, top_k=quota, record_year=year, **filters) if quota else []
        buckets.append(deque(item for item in items if str(item.date or '').startswith(f'{year}-')))
    result, seen = [], set()
    while any(buckets) and len(result) < top_k:
        for bucket in buckets:
            if not bucket:
                continue
            item = bucket.popleft()
            key = (item.house, item.question_id, item.chunk_id)
            if key not in seen:
                result.append(item)
                seen.add(key)
    return result, years


def period_coverage(groups, years: list[int]) -> dict | None:
    if not years:
        return None
    counts = {str(year): sum(str(g.date or '').startswith(f'{year}-') for g in groups) for year in years}
    missing = [year for year in years if not counts[str(year)]]
    return {'requested_years': years, 'basis': 'parliamentary_record_date',
            'records_in_context': counts, 'missing_years': missing,
            'note': 'Record dates do not establish the observation period, operational status, or completeness of the figures inside them.'}


def coverage_context(coverage: dict | None) -> str:
    if not coverage:
        return ''
    counts = ', '.join(f'{y}: {n} record(s)' for y, n in coverage['records_in_context'].items())
    missing = ', '.join(map(str, coverage['missing_years'])) or 'none'
    return ('=== COMPARISON SOURCE COVERAGE ===\n'
            f'Calendar years requested: {coverage["requested_years"]}. Retrieved context by record date: {counts}.\n'
            f'Years with no selected source: {missing}.\n'
            'Compare only facts explicitly established in the supplied passages. If a requested period lacks evidence, identify the gap; never fill it with another year. '
            'Publication/answer dates are not observation dates. Preserve the stated as-of dates and separate operational commissioning from planned or in-progress work. '
            'Use a concise comparison table with columns for metric, observation/as-of date, value with its original unit, scope/version/status, and source citation. '
            'Keep locomotive counts, station counts, route kilometres, trackside equipment and commissioned coverage on distinct rows. Never turn a locomotive count into route kilometres. '
            'Do not add figures for different versions or scopes or claim growth between incomparable measures. Keep the summary brief and cite every numerical statement, including in the summary. '
            'Records from both years do not by themselves prove that comparable figures exist.\n'
            '=== END COMPARISON SOURCE COVERAGE ===')
