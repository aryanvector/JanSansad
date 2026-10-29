"""Complementary numeric passages within an existing per-record budget.

Lexical selection only; it does not certify units, entailment or completeness.
"""
import re

FACETS = {
    'labs': r'\b(?:labs?|laborator(?:y|ies))\b',
    'classrooms': r'\bclassrooms?\b',
    'vacancies': r'\b(?:vacanc(?:y|ies)|vacant)\b',
    'capacity': r'\bcapacit(?:y|ies)\b',
    'admissions': r'\badmissions?\b',
    'users': r'\b(?:users?|enrolments?|enrollments?)\b',
    'calls': r'\bcalls?\b',
    'cells': r'\bcells?\b',
    'languages': r'\blanguages?\b',
    'allocation': r'\b(?:allocat\w*|budget\w*)\b',
    'expenditure': r'\b(?:expenditure|spent|spending)\b',
    'sanction': r'\b(?:sanction\w*)\b',
}
NUMBER = re.compile(r'(?<!\w)\d+(?:[,.]\d+)*(?!\w)')


def numeric_facets(text, requested):
    # A question premise must not beat its later answer/table just by repeating
    # the requested words. Only strip when an explicit ANSWER header exists.
    header = re.search(r'(?:^|\n| {2,})(?:##\s*)?ANSWER\b', text)
    if header:
        text = text[header.end():]
    hits = set()
    for name in requested:
        for match in re.finditer(FACETS[name], text, re.I):
            # Counts in extracted tables normally follow their row labels;
            # money may precede "allocated". A short local window avoids
            # assigning arbitrary numbers elsewhere in the record to a facet.
            start = max(0, match.start()-70) if name in ('allocation','expenditure','sanction') else match.end()
            if NUMBER.search(text[start:match.end()+100]):
                hits.add(name)
                break
    return hits


def complementary_order(ranked, query):
    """Return the same passages, reordered by new requested numeric coverage.

    Original relevance order breaks ties. Consumers still enforce M/N/C.
    Single-facet/non-numeric requests retain the previous ranking.
    """
    requested = {name for name,pattern in FACETS.items() if re.search(pattern,query,re.I)}
    if len(requested)<2 or len(ranked)<2:
        return ranked
    coverage = [numeric_facets(c.text,requested) for c in ranked]
    remaining = list(range(len(ranked)))
    covered, result = set(), []
    while remaining:
        index = max(remaining,key=lambda i:(len(coverage[i]-covered),-i))
        result.append(ranked[index]);covered.update(coverage[index]);remaining.remove(index)
    return result
