"""Source-linked people attached to records; biographies are never LLM-generated."""
from __future__ import annotations

import ast
import html
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from lok_sabha_rag.config import DATA_DIR
from lok_sabha_rag.api.routes.question_text import QuestionTextRequest, _retriever

router = APIRouter()
_lock = threading.Lock()
_index = None
_index_time = 0
_cache_dir = DATA_DIR / 'profiles'


def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', str(value or '')))).strip()


def safe_photo(value):
    value = str(value or '')
    parsed = urlparse(value)
    return value if parsed.scheme == 'https' and parsed.hostname == 'sansad.in' else None


def fetch_json(url):
    with urlopen(Request(url, headers={'User-Agent': 'SansadAI/1.0', 'Accept': 'application/json'}), timeout=8) as response:
        return json.loads(response.read(5_000_000))


def cached_json(key, url):
    """Persist only a public source response; serve cache with its actual fetch date."""
    path = _cache_dir / (key + '.json')
    old = None
    try:
        old = json.loads(path.read_text())
        if time.time() - old['time'] < 86400:
            return old
    except (OSError, ValueError, KeyError):
        pass
    try:
        entry = {'time': time.time(), 'data': fetch_json(url), 'source': url}
        _cache_dir.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(entry), encoding='utf-8')
        temp.replace(path)
        return entry
    except Exception:
        return old


def normalise(name):
    name = clean(name).lower()
    name = re.sub(r'\b(shri|smt|shrimati|dr|adv|prof|ms|mr|mrs|late|hon)\b\.?', '', name)
    if ',' in name:
        surname, given = name.split(',', 1)
        name = given + ' ' + surname
    # Preserve initial order: R.K. Singh and K.R. Singh are different people.
    return ''.join(re.findall(r'[a-z]+', name))


def directory():
    global _index, _index_time
    if _index is not None and time.time() - _index_time < 86400:
        return _index
    with _lock:
        if _index is not None and time.time() - _index_time < 86400:
            return _index
        by_id, aliases = {}, {}
        # Ascending order: latest source profile wins. Never claim historical party.
        for lok in (16, 17, 18):
            source = f'https://sansad.in/api_ls/member?loksabha={lok}&page=1&size=1000&locale=en'
            entry = cached_json(f'members-{lok}', source)
            for member in (entry or {}).get('data', {}).get('membersDtoList', []):
                code = member.get('mpsno')
                if not code:
                    continue
                by_id[code] = {k: member.get(k) for k in ('mpsno','mpFirstLastName','mpLastFirstName','partyFname','stateName','constName','profession','qualification','imageUrl','lsExpr','status')}
                by_id[code]['retrieved_at'] = datetime.fromtimestamp(entry['time'], timezone.utc).isoformat()
                for name in (member.get('mpFirstLastName'), member.get('mpLastFirstName')):
                    if name:
                        aliases.setdefault(normalise(name), set()).add(code)
                parts = clean(member.get('mpFirstLastName')).split()
                if len(parts) >= 2:
                    initials = ' '.join(p[0] for p in parts[:-1]) + ' ' + parts[-1]
                    aliases.setdefault(normalise(initials), set()).add(code)
            # The dataset supplies the spellings used in retrieved records.
            if lok in (17, 18):
                entry = cached_json(f'aliases-{lok}', f'https://huggingface.co/datasets/opensansad/lok-sabha-qa/resolve/main/supplementary/{lok}/members.json')
                for member in (entry or {}).get('data', []):
                    if member.get('mpName') and member.get('mpNo'):
                        aliases.setdefault(normalise(member['mpName']), set()).add(member['mpNo'])
        _index = (by_id, aliases)
        _index_time = time.time() if by_id else time.time() - 86340
        return _index


def person(name, by_id, aliases, lok_no=None):
    candidates = set(aliases.get(normalise(name), set()))
    # A full first/surname may omit a middle name in the answer heading.
    # Accept this spelling only when it resolves to one official member.
    if not candidates:
        tokens = re.findall(r'[a-z]+', clean(name).lower())
        tokens = [t for t in tokens if t not in ('shri','smt','shrimati','dr','mr','mrs')]
        if len(tokens) >= 2 and len(tokens[0]) > 1:
            for code, member in by_id.items():
                full = re.findall(r'[a-z]+', clean(member.get('mpFirstLastName')).lower())
                if full and full[0] == tokens[0] and full[-1] == tokens[-1] and all(t in full for t in tokens):
                    candidates.add(code)
    if len(candidates) > 1 and lok_no:
        candidates = {code for code in candidates if str(lok_no) in re.findall(r'\d+', str(by_id.get(code, {}).get('lsExpr', '')))}
    if len(candidates) != 1:
        return {'name': clean(name), 'matched': False}
    code = next(iter(candidates))
    item = by_id.get(code)
    if not item:
        return {'name': clean(name), 'matched': False}
    return {'name': clean(item['mpFirstLastName'] or name), 'matched': True, 'id': code,
            'photo_url': safe_photo(item['imageUrl']), 'party': clean(item['partyFname']),
            'state': clean(item['stateName']), 'constituency': clean(item['constName']),
            'profile_url': f'https://sansad.in/ls/members/biographyM/{code}?from=members',
            'retrieved_at': item['retrieved_at']}


def names(value):
    if not value:
        return []
    if isinstance(value, list):
        return [clean(x) for x in value if x]
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, list):
            return [clean(x) for x in parsed if x]
    except (ValueError, SyntaxError):
        pass
    return [clean(x) for x in str(value).split(';') if clean(x)]


def answerer(text):
    # Only inspect the answer heading, not honourifics inside the question/body.
    text = html.unescape(text)
    marker = re.search(r'(?im)^[ \t]*(?:#+[ \t]*)?A[ \t]*N[ \t]*S[ \t]*W[ \t]*E[ \t]*R[ \t]*:?[ \t]*$', text)
    if not marker:
        return None
    section = text[marker.end():marker.end()+1200]
    # A minister mentioned in the answer body is not the answering person.
    section = re.split(r'(?im)^[ \t]*(?:[-*][ \t]*)?\([a-z]\)[ \t]*', section, maxsplit=1)[0]
    match = re.search(r'(?im)^[ \t]*(?:#+[ \t]*)?((?:THE[ \t]+)?MINISTER[^()]{0,600})\(\s*((?:SHRI|SMT\.?|SHRIMATI|DR\.?)\s+[^()]{2,120})\)', section)
    if not match:
        return None
    return {'name': clean(match[2]).title(), 'role_in_record': clean(match[1]).replace('#', '').strip()}


@router.post('/parliamentary-context')
def context(req: QuestionTextRequest):
    chunks = _retriever._fetch_leading_chunks(c=4, question_id=req.question_id, lok_no=req.lok_no,
        session_no=req.session_no, ques_no=req.ques_no, qtype=req.type)
    if not chunks:
        raise HTTPException(404, 'No evidence found for this parliamentary question.')
    text = '\n\n'.join(c.text or '' for c in chunks)
    first = chunks[0]
    if getattr(first,'house',None)=='rajya_sabha':
        from . import rs_profiles
        return rs_profiles.question_context(chunks,text)
    by_id, aliases = directory()
    lok_no = req.lok_no or (req.question_id.split('_')[0] if req.question_id else None)
    asked = [person(n, by_id, aliases, lok_no) for n in names(first.asked_by)]
    answered = answerer(text)
    if answered:
        identity = person(answered['name'], by_id, aliases, lok_no)
        # A Rajya Sabha minister may answer a Lok Sabha question. The answer
        # heading establishes the role; biography matching remains independent.
        if not identity['matched']:
            from . import rs_profiles
            alternative = rs_profiles.person(answered['name'])
            if alternative['matched']:
                identity = alternative
        answered = {**identity, 'role_in_record': answered['role_in_record']}
    date = re.search(r'ANSWERED\s+ON\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})', text, re.I)
    return {'asked_by': asked, 'answered_by': answered, 'record_date': getattr(first,'date',None) or (date[1] if date else None),
            'ministry': first.ministry, 'source_url': first.pdf_url,
            'profile_note': 'Profile details reflect the linked source when fetched, not necessarily the party or constituency at the date of this answer.',
            'answerer_note': None if answered else 'The answering person could not be identified reliably from the indexed answer heading. Check the original record.'}


@router.get('/profiles/{member_id}')
def profile(member_id: int):
    if not 1 <= member_id <= 100000:
        raise HTTPException(404, 'Member profile not found.')
    bio = cached_json(f'bio-{member_id}', f'https://sansad.in/api_ls/member/{member_id}?locale=en')
    if not bio or not isinstance(bio['data'], dict) or not bio['data'].get('mpsno'):
        raise HTTPException(503, 'Official profile is unavailable. Please use the source link.')
    positions = cached_json(f'positions-{member_id}', f'https://sansad.in/api_ls/member/positionHeld?mpCode={member_id}&locale=en')
    b = bio['data']
    return {'id': member_id, 'name': clean(b.get('firstLastName') or b.get('lastFirstName')),
            'photo_url': safe_photo(b.get('photoUrl')), 'party': clean(b.get('partyFname')),
            'state': clean(b.get('stateName')), 'education': clean(b.get('education')),
            'date_of_birth': clean(b.get('dob')), 'terms': clean(b.get('loksabhaExpr')),
            'career': [{'period': clean(x.get('period')), 'position': clean(x.get('positionHeld'))} for x in (positions or {}).get('data', []) if isinstance(x, dict)],
            'career_available': positions is not None,
            'retrieved_at': datetime.fromtimestamp(bio['time'], timezone.utc).isoformat(),
            'career_retrieved_at': datetime.fromtimestamp(positions['time'], timezone.utc).isoformat() if positions else None,
            'profile_url': f'https://sansad.in/ls/members/biographyM/{member_id}?from=members'}


@router.get('/profile-photo/{member_id}')
def profile_photo(member_id: int):
    """Serve an official directory portrait without accepting arbitrary URLs."""
    members, _ = directory()
    url = safe_photo(members.get(member_id, {}).get('imageUrl'))
    if not url:
        raise HTTPException(404, 'Official portrait unavailable.')
    try:
        with urlopen(Request(url, headers={'User-Agent': 'SansadAI/1.0'}), timeout=8) as result:
            kind = result.headers.get_content_type()
            if kind not in ('image/jpeg', 'image/png', 'image/webp') or not safe_photo(result.url):
                raise ValueError('Invalid official portrait response')
            data = result.read(3_000_001)
            if len(data) > 3_000_000:
                raise ValueError('Portrait exceeds size limit')
        return Response(data, media_type=kind, headers={'Cache-Control':'public, max-age=86400','X-Content-Type-Options':'nosniff'})
    except Exception:
        raise HTTPException(503, 'Official portrait temporarily unavailable.')
