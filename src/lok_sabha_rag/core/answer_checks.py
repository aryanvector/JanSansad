"""Bounded, deterministic checks. A clear result is NOT semantic verification.

Checks literal numeric support, explicit addition/subtraction, explicit answer
dates, and a narrow approved-outlay/spending confusion. No model judges itself.
"""
from __future__ import annotations

import re
from decimal import Decimal

from lok_sabha_rag.core.scoped_retrieval import date_spans

CITE = re.compile(r'\[Q(\d+)\]')
NUMBER = r'\d+(?:,\d{2,3})*(?:\.\d+)?'
NUMBERS = re.compile(rf'(?<![\w.]){NUMBER}(?!\w|\.\d)')
EQUATION = re.compile(rf'({NUMBER}(?:\s*[+−-]\s*{NUMBER}){{1,7}})\s*=\s*({NUMBER})')
LIMIT = 'Limited checks only: number presence does not establish the correct unit, population, period, attribution or meaning. No general fact-check or automatic unit conversion is performed.'


def number(value):
    return Decimal(value.replace(',', ''))


def values(text):
    return {number(m.group()) for m in NUMBERS.finditer(text)}


def _math_text(text):
    """Normalise explicit addition/subtraction typography, never convert units."""
    unit = r'(?:kms?|kilomet(?:er|re)s?|crores?|lakhs?|millions?|billions?|rupees)'
    families = set()
    for m in re.finditer(rf'\b{unit}\b', text, re.I):
        value=m.group().casefold()
        families.add('km' if re.fullmatch(r'kms?|kilomet(?:er|re)s?',value) else value.rstrip('s'))
    # Leave mixed scales/units unnormalised rather than accepting an addition
    # such as lakh + crore by stripping the distinction.
    if len(families)>1:
        return text
    text=re.sub(rf'\\text\{{\s*({unit})\s*\}}',r' \1 ',text,flags=re.I)
    text=re.sub(rf'\b{unit}\b',' ',text,flags=re.I)
    text=text.replace('$','').replace('(',' ').replace(')',' ')
    return re.sub(r'\b(?:equals|yields(?:\s+a)?(?:\s+(?:combined|total))?(?:\s+(?:length|amount|value|sum))?(?:\s+of)?)\b','=',text,flags=re.I)


def _missing_source_dates(text):
    """Only exempt dates in explicit local missing-record statements.

    This does not verify the absence claim or suppress any other number.
    Archive-wide absence assertions and positive record-date claims stay checked.
    """
    spans=[]
    for start,end,_ in date_spans(text):
        before=text[max(0,start-180):start]
        before=re.split(r'[.;!?]\s+|\b(?:but|however|whereas)\b',before,flags=re.I)[-1]
        record=r'(?:answer|reply|response|record)\s+(?:dated|from|of|on)\s*$'
        scoped=bool(re.search(r'\b(?:evidence|passages|excerpts|context|selected records)\b',before,re.I))
        negative=bool(re.search(r'\b(?:does not contain|do not contain|does not include|does not provide|lacks?)\b',before,re.I))
        after=re.split(r'[.;!?]\s+|\b(?:but|however|whereas)\b',text[end:end+150],flags=re.I)[0]
        trailing=bool(re.search(r'\b(?:is|are|was|were)\s+(?:entirely\s+)?(?:missing|absent|not (?:present|available|found|retrieved))\s+(?:from|in)\s+(?:the\s+)?(?:supplied|provided|selected|retrieved)\s+(?:evidence|passages|excerpts|context)\b',after,re.I))
        if re.search(record,before,re.I) and ((scoped and negative) or trailing):
            spans.append((start,end))
    return spans


def _equations(text, supported):
    issues, derived = [], set()
    for match in EQUATION.finditer(_math_text(text)):
        tokens = re.findall(rf'{NUMBER}|[+−-]', match[1])
        operands = [number(t) for t in tokens[::2]]
        result = operands[0]
        for op, operand in zip(tokens[1::2], operands[1:]):
            result = result + operand if op == '+' else result - operand
        if result != number(match[2]):
            issues.append(('arithmetic_mismatch', f'Explicit arithmetic does not balance: {match[0]}. Computed result: {result}.'))
        elif all(n in supported for n in operands):
            derived.add(result)
    return issues, derived


def audit_answer(answer, groups):
    """Accept EvidenceGroup objects or serialized API evidence groups."""
    def get(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

    sources = {}
    for g in groups:
        idx = int(get(g, 'group_index'))
        text = '\n'.join(get(c, 'text', '') or '' for c in get(g, 'chunks', []))
        sources[idx] = {'text': text, 'date': str(get(g, 'date') or '')[:10]}
    issues = []
    checked = 0
    all_support = set().union(*(values(s['text'] + ' ' + s['date']) for s in sources.values())) if sources else set()

    def add(code, claim, message):
        item = {'code': code, 'claim': claim[:400], 'message': message}
        if not any(i['code'] == code and i['claim'] == item['claim'] and i['message'] == message for i in issues):
            issues.append(item)

    # Lines keep table rows/bullets intact; decimal points must not split claims.
    for raw in answer.splitlines():
        line = raw.strip()
        if not line or re.fullmatch(r'[\s|:\-]+', line):
            continue
        ids = {int(m[1]) for m in CITE.finditer(line)}
        invalid = ids - sources.keys()
        if invalid:
            add('invalid_citation', line, 'The claim references unavailable evidence.')
        cited = [sources[i] for i in sorted(ids) if i in sources]
        clean = CITE.sub('', line).replace('**', '').replace('`', '')
        # Ignore markdown list indices and version labels, not actual figures.
        clean = re.sub(r'^\s*\d+[.)]\s+', '', clean)
        clean = re.sub(r'\b(?:version|ver\.?)\s*\d+(?:\.\d+)?', '', clean, flags=re.I)
        missing_date_spans = _missing_source_dates(clean)
        numeric_text=clean
        for start,end in reversed(missing_date_spans):
            numeric_text=numeric_text[:start]+' '+numeric_text[end:]
        nums = values(numeric_text)
        nums = {n for n in nums if n >= 10}  # Small counts need future semantic checks.
        if not nums:
            continue
        checked += 1
        text = '\n'.join(s['text'] for s in cited)
        support = values(text + ' ' + ' '.join(s['date'] for s in cited)) if cited else all_support
        arithmetic, derived = _equations(clean, support)
        for code, message in arithmetic:
            add(code, line, message)
        missing = sorted(nums - support - derived)
        if missing:
            add('number_not_in_passages', line,
                'These figures are absent from the cited passages' + ('' if cited else ' (no citation on this line)') + ': ' + ', '.join(str(n) for n in missing) + '. Supply a supported calculation or omit the claim.')

        # Only an explicit reply/answer date is compared with record metadata.
        # Observation, launch and advisory dates are deliberately not equated.
        for start, end, date in date_spans(clean):
            if (start,end) in missing_date_spans:
                continue
            prefix = clean[max(0, start-55):start]
            if re.search(r'\b(?:answer(?:ed)?|repl(?:y|ies)|response|record)\s+(?:(?:dated|on|of|in)\s+)?$', prefix, re.I):
                dates = {s['date'] for s in cited if s['date']}
                if dates and date not in dates:
                    add('answer_date_mismatch', line, f'Claimed answer date {date} differs from the cited record dates: {", ".join(sorted(dates))}.')

        # Deliberately narrow: flag a spend assertion only if the same number
        # appears beside approval/outlay in evidence, with no spend evidence.
        if cited and re.search(r'\b(?:spent|expenditure incurred|actually expended)\b', clean, re.I) and not re.search(r'\b(?:not|no|unknown|does not|cannot|not established)\b', clean, re.I):
            for n in nums:
                windows = []
                for m in NUMBERS.finditer(text):
                    if number(m.group()) == n:
                        windows.append(text[max(0, m.start()-85):m.end()+85])
                if windows and any(re.search(r'\b(?:approved|approval|outlay)\b', w, re.I) for w in windows) and not any(re.search(r'\b(?:spent|expenditure|utili[sz]ed)\b', w, re.I) for w in windows):
                    add('spending_status_review', line, f'{n} appears near approval/outlay language; the selected passages do not establish that it was spent.')
    return {'status': 'review_needed' if issues else 'limited_checks_clear',
            'checked_numeric_lines': checked, 'issues': issues[:20], 'issue_count': len(issues),
            'limitations': LIMIT}


def generate_checked(synthesizer, query, context, groups):
    """One initial answer, at most one revision; retain unresolved warnings."""
    from lok_sabha_rag.core.ai_provider import GenerationError

    answer = synthesizer.generate(query=query, context=context)
    initial = audit_answer(answer, groups)
    report = {**initial, 'repair_attempted': False, 'initial_issue_count': initial['issue_count']}
    if not initial['issues']:
        return answer, report
    instructions = '\n'.join(f'- {i["code"]}: {i["message"]} Claim: {i["claim"]}' for i in initial['issues'])
    repair_context = context + '\n\n=== DRAFT TO REVISE (not evidence) ===\n' + answer + '\n=== AUTOMATED REVIEW (not evidence) ===\n' + instructions + '\nRewrite the complete answer using ONLY the original evidence above. Omit unsupported extra details. Do not treat this draft or review as a source. Preserve dates, units, qualifiers and approved/released/spent/completed distinctions. If a derived total is needed, show a simple explicit addition or subtraction equation with cited operands; otherwise omit that total. Cite every factual claim. Never manufacture evidence to satisfy a check.'
    report['repair_attempted'] = True
    try:
        revised = synthesizer.generate(query=query, context=repair_context)
    except GenerationError:
        report['repair_failed'] = True
        return answer, report
    # Keep the revision only if the deterministic issue count improves.
    final = audit_answer(revised, groups)
    if final['issue_count'] < initial['issue_count']:
        return revised, {**final, 'repair_attempted': True, 'repair_applied': True,
                         'initial_issue_count': initial['issue_count']}
    report['repair_applied'] = False
    return answer, report
