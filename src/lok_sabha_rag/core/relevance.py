"""Conservative, record-level topic gate for user-facing retrieval.

Nearest neighbours and fused ranks are not proof of relevance. Require a
content anchor in the returned record before displaying it or invoking an LLM.
This intentionally favours abstention; it is not semantic entailment scoring.
"""
import re

NO_RESULTS = 'No results found. Please try again with a different keyword or change your filters.'
_STOP = set('''a an the and or of to in on for from by with at as is are was were
be been being do does did has have had how what which who whom when where why
can could would should will shall may me my your you i we our us it its this
that these those please tell explain describe show give find search about
information details detail regarding related question questions answer answers
name names mean meaning india indian government country hello hi greetings
parliament parliamentary lok sabha rajya record records reply replies compare
comparison between versus vs reported reporting report reports year years date
dates latest recent current currently total many much number numbers available
introduced introduce introduction developed develop development developments
system systems work works done made implemented implementation progress
january february march april june july august september october november december
kya hai hain ka ki ke ko mein me se aur kab kis mujhe batao bata par tha thi
है हैं क्या कब किस का की के को में से और मुझे बताओ पर था थी'''.split())
_ALIASES = {
    'jobs':'employment', 'job':'employment', 'unemployment':'employment',
    'trains':'railway', 'train':'railway', 'railways':'railway',
    'schools':'school', 'hospitals':'hospital', 'ministers':'minister',
}

def tokens(text):
    words = re.findall(r'[^\W\d_]+', str(text or '').casefold(), re.UNICODE)
    return {_ALIASES.get(w, w[:-1] if len(w)>4 and w.endswith('s') else w)
            for w in words if w not in _STOP and len(w)>1}

def relevant_items(query, items):
    anchors = tokens(query)
    if not anchors:
        return []
    # Aggregate candidate chunks of the same record; preserve original ranking.
    records = {}
    def key(item):
        return (getattr(item, 'house', ''), getattr(item, 'question_id', None)
                or getattr(item, 'chunk_id', id(item)))
    for item in items:
        words = tokens(' '.join(str(getattr(item, f, '') or '')
                               for f in ('subject', 'text', 'asked_by', 'ministry')))
        records.setdefault(key(item), set()).update(words)
    accepted = {k for k, words in records.items() if anchors & words}
    return [item for item in items if key(item) in accepted]
