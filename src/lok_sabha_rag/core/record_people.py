"""Source-backed debate participants and bill presenters; never LLM-inferred."""
import hashlib
import json
import re
import sqlite3
import uuid
import unicodedata
from contextlib import closing
from datetime import datetime,timezone
from lok_sabha_rag.config import DATA_DIR
from lok_sabha_rag.core import debate_store,debate_fulltext

def clean(value):return re.sub(r'\s+',' ',str(value or '')).strip()

def name_key(name):
    name=re.sub(r'\b(?:shrimati|shri|smt|dr|prof)\b\.?\s*','',name,flags=re.I)
    return ''.join(c for c in unicodedata.normalize('NFKC',name.casefold()) if unicodedata.category(c)[0] in 'LMN')

def speaker_turns(text):
    patterns=[r'(?:^|\n)[ \t]*((?:THE\s+)?MINISTER[^:]{0,450}?\(\s*((?:SHRI|SHRIMATI|SMT\.?|DR\.?)\s+[^)]{2,100})\))\s*:',
              r'(?:^|\n)[ \t]*((?:SHRI|SHRIMATI|SMT\.?|DR\.?)\s+[A-Z][A-Z .\n\'-]{2,100}(?:\s*\([^:\n]{1,100}\))?)\s*:']
    hits={}
    for i,pattern in enumerate(patterns):
        for m in re.finditer(pattern,text):
            name=clean(m[2] if i==0 else re.sub(r'\([^)]*\)','',m[1]))
            name=re.sub(r'^(?:SHRI|SHRIMATI|SMT\.?|DR\.?)\s+','',name).strip()
            if len(re.findall('[A-Za-z]+',name))>=2:hits[m.start()]={'name':name.title(),'heading':clean(m[1]),'end':m.end(),'start':m.start()}
    turns=sorted(hits.values(),key=lambda h:h['start'])
    for i,t in enumerate(turns):
        fragment=text[t['end']:turns[i+1]['start'] if i+1<len(turns) else len(text)]
        boundary=re.search(r'(?im)^[ \t]*(?:HON\.?[ \t]*(?:CHAIRPERSON|CHAIRMAN|SPEAKER)|माननीय\s+(?:सभापति|अध्यक्ष)|(?:श्री|श्रीमती|डॉ\.?|SHRI|SHRIMATI|SMT\.?|DR\.?)[^\n:]{1,100})\s*:',fragment)
        if boundary:fragment=fragment[:boundary.start()]
        t['body']=clean(fragment)
    return turns

def introduction_actor(text):
    for direct in (True,False):
        for turn in speaker_turns(text):
            body=turn['body'][:650]
            pattern=(r'\bI\s+(?:hereby\s+)?introduce\s*\*?\s+(?:the|a)\s+Bill\b' if direct else r'\bI\s+(?:(?:rise\s+to|beg\s+to)\s+)?move\s+(?:for\s+)?leave\s+to\s+introduce\b')
            m=re.search(pattern,body,re.I)
            if not m or m.start()>=180:continue
            prefix=body[:m.start()]
            allowed=re.fullmatch(r"(?:(?:sir|madam|hon\.?\s*(?:chairperson|chairman|speaker)(?:\s+sir)?|mr\.?\s+speaker|with\s+your\s+permission)|[\s,.;:!?-])*",prefix,re.I)
            if allowed:return {'name':turn['name'],'role':'Introduced the bill' if direct else 'Moved the introduction motion','excerpt':turn['heading']+': '+body[:m.end()]+'.'}
    return None

def debate_people(row):
    indexed=debate_fulltext.get(row['question_id'])
    data=indexed if indexed and indexed['status']=='extracted' else debate_store.transcript(row)
    text=data.get('text','') if data.get('status')=='extracted' else ''
    source=row.get('source_pdf_url') or (indexed or {}).get('record',{}).get('source_pdf_url') or row['source_url']
    people={name_key(n):{'name':n,'roles':['Listed debate participant'],'source_url':row['source_url'],'excerpt':None} for n in row.get('mp_names',[]) if clean(n)}
    for turn in speaker_turns(text):
        key=name_key(turn['name']);entry=people.setdefault(key,{'name':turn['name'],'roles':[],'source_url':source,'excerpt':None})
        if 'Named speaker in transcript' not in entry['roles']:entry['roles'].append('Named speaker in transcript')
        entry.update(source_url=source,excerpt=turn['heading']+': '+turn['body'][:350])
    return {'kind':'debate','record_id':row['question_id'],'record_date':row['date'],'house':row['house'],'people':list(people.values()),'source_url':source,
        'note':'Participants come from the official catalogue. A speaker role requires an explicit transcript heading; extraction may be incomplete. Participation does not establish a vote or position.'}

def bill_fingerprint(row):
    return hashlib.sha256(json.dumps(['attribution-v3',row['id'],row.get('introduced_by'),row.get('introduced_date'),row.get('origin_house'),row['title']],sort_keys=True).encode()).hexdigest()

def introduction_candidates(row):
    date=row.get('introduced_date');house=row.get('origin_house')
    if not date or house not in ('Lok Sabha','Rajya Sabha'):return []
    path=debate_store.ls_path() if house=='Lok Sabha' else debate_store.path()
    if not path.exists():return []
    stop={'the','a','an'};terms={t for t in re.findall(r'[a-z0-9]+',row['title'].casefold()) if t not in stop}
    if not terms:return []
    with closing(sqlite3.connect(path)) as db:rows=[json.loads(x[0]) for x in db.execute('SELECT record FROM records WHERE date=?',(date,))]
    candidates=[];allowed={'introduced','introduction','as','in','lok','sabha','rajya','motion','to','leave','for'}
    for debate in rows:
        title=debate['subject'].casefold()
        if 'introduc' not in title or 'bill' not in title:continue
        tokens={t for t in re.findall(r'[a-z0-9]+',title) if t not in stop};extras=tokens-terms
        if terms<=tokens and all(t in allowed or re.fullmatch('introduced[0-9]+',t) for t in extras):candidates.append(debate)
    return sorted(candidates,key=lambda r:r['question_id'])[:3]

def introduction_section(text,title):
    words=re.findall(r'[A-Za-z0-9]+',title)
    words=[w for w in words if w.casefold()!='the' and not re.fullmatch(r'(?:19|20)[0-9]{2}',w)]
    pattern=r'(?im)(?:^|\n)[ \t]*(?:THE\s+)?'+r'[\W_]*'.join(re.escape(w) for w in words)
    own=re.search(pattern,text)
    if not own:return ''
    tail=text[own.end():]
    next_bill=re.search(r'(?im)^\s*(?:THE\s+)?[A-Z][A-Za-z0-9 ,()\-]{3,180}\bBill\b[^\n]{0,80}\bIntroduced\b',tail)
    end=own.end()+next_bill.start() if next_bill else len(text)
    return text[own.start():min(end,own.start()+20000)]

def bill_people(row):
    house='lok_sabha' if row.get('origin_house')=='Lok Sabha' else 'rajya_sabha'
    base={'kind':'bill','record_id':row['id'],'record_date':row.get('introduced_date'),'house':house,'people':[],
        'source_url':row['sources'][0] if row.get('sources') else 'https://sansad.in/ls/legislation/bills',
        'note':'Presenter means the person named in the introduction record, not every speaker or the sole bill author. Profile details may describe a later period.'}
    name=clean(row.get('introduced_by'))
    if name and name.casefold() not in ('--','-','n/a','na','not available','none'):
        return {**base,'people':[{'name':name,'roles':['Introduced by - official bill catalogue'],'source_url':base['source_url'],'excerpt':None}],'attribution_method':'official_catalogue'}
    cache=DATA_DIR/'bills'/'presenters'/(row['id']+'.json');fingerprint=bill_fingerprint(row)
    try:
        old=json.loads(cache.read_text(encoding='utf-8'))
        if old.get('fingerprint')==fingerprint:return old['result']
    except (OSError,ValueError):pass
    for debate in introduction_candidates(row):
        data=debate_store.transcript(debate)
        if data.get('status')!='extracted':continue
        actor=introduction_actor(introduction_section(data['text'],row['title']))
        if not actor:continue
        source=debate.get('source_pdf_url') or debate['source_url']
        result={**base,'people':[{'name':actor['name'],'roles':[actor['role']+' - official introduction debate'],'source_url':source,'excerpt':actor['excerpt']}],
            'source_url':source,'attribution_method':'explicit_introduction_motion','introduction_debate_id':debate['question_id']}
        cache.parent.mkdir(parents=True,exist_ok=True);stage=cache.with_name(uuid.uuid4().hex+'.pending')
        stage.write_text(json.dumps({'fingerprint':fingerprint,'result':result,'checked_at':datetime.now(timezone.utc).isoformat()}),encoding='utf-8');stage.replace(cache)
        return result
    return {**base,'attribution_method':'unavailable','note':base['note']+' The presenter could not be verified from the available catalogue and introduction transcript; no name has been inferred.'}
