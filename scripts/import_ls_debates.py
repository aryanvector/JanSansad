"""Import official Lok Sabha Part-II metadata; resolve PDFs only when needed."""
import argparse
import gzip
import json
import re
import sqlite3
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen

API='https://elibrary.sansad.in/server/api/discover/search/objects'
SCOPE='03c67f26-e547-4c6f-914d-e4b443281a8c'


def number(value):
    s=str(value or '').strip().upper()
    if s.isdigit():return int(s)
    if not re.fullmatch('[IVXLCDM]+',s):return None
    values={'I':1,'V':5,'X':10,'L':50,'C':100,'D':500,'M':1000}
    return sum((-1 if i+1<len(s) and values[c]<values[s[i+1]] else 1)*values[c] for i,c in enumerate(s))


def normalize(obj,start,end):
    md=obj.get('metadata',{})
    def val(key):return str((md.get(key) or [{}])[0].get('value') or '').strip()
    date=val('dc.date.issued')[:10]
    try:datetime.strptime(date,'%Y-%m-%d')
    except ValueError:return None,'invalid_date'
    if not f'{start}-01-01'<=date<=f'{end}-12-31':return None,'outside_range'
    if 'part 2' not in val('dc.type').casefold() or val('dc.identifier.questionnumber'):return None,'qa_excluded'
    title=val('dc.title')
    if not title:return None,'missing_title'
    item=str(uuid.UUID(obj['uuid']))
    return dict(question_id='LS_D_'+item,content_type='debate',house='lok_sabha',
        lok_no=number(val('dc.identifier.loksabhanumber')),session_no=number(val('dc.identifier.sessionnumber')),
        ques_no=None,type='DEBATE',date=date,subject=title,debate_category=val('dc.type.debate'),
        mp_names=[str(x['value']).strip() for x in md.get('dc.contributor.members',[]) if x.get('value')],
        ministry='; '.join(x['value'] for x in md.get('dc.relation.ministry',[]) if x.get('value')),
        language=[val('dc.language.iso')],original_pages='',files=[],source_record_id=item,
        source_url=val('dc.identifier.uri') or f'https://elibrary.sansad.in/items/{item}',source_pdf_url=None,
        bundles_url=f'https://elibrary.sansad.in/server/api/core/items/{item}/bundles'),None


def run(output,start,end):
    root=Path(output);root.mkdir(parents=True,exist_ok=True);cache=root/'source-pages';cache.mkdir(exist_ok=True)
    def fetch(page):
        dest=cache/f'{start}-{end}-{page}.json.gz'
        if dest.exists():return json.loads(gzip.decompress(dest.read_bytes()))
        params=dict(scope=SCOPE,page=page,size=100,sort='dc.date.issued,DESC',query=f'dc.date.issued:[{start}-01-01 TO {end}-12-31]')
        for attempt in range(3):
            try:
                with urlopen(Request(API+'?'+urlencode(params),headers={'User-Agent':'SansadAI/1.0'}),timeout=30) as response:raw=response.read(20_000_001)
                if len(raw)>20_000_000:raise ValueError('Metadata page too large')
                data=json.loads(raw)['_embedded']['searchResult'];break
            except Exception:
                if attempt==2:raise
                time.sleep(attempt+1)
        dest.write_bytes(gzip.compress(json.dumps(data).encode()));return data
    first=fetch(0);total=first['page']['totalElements'];page_count=first['page']['totalPages']
    print(f'Official LS Part-II range reports {total} entries in {page_count} pages',flush=True)
    rows=[]
    def consume(data):
        if data['page']['totalElements']!=total:raise RuntimeError('Source changed during import. Retry with a fresh cache.')
        rows.extend(o['_embedded']['indexableObject'] for o in data.get('_embedded',{}).get('objects',[]))
    consume(first)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for i,data in enumerate(pool.map(fetch,range(1,page_count)),2):
            consume(data)
            if i%25==0:print(f'LS metadata pages: {i}/{page_count}',flush=True)
    if len(rows)!=total:raise RuntimeError(f'Incomplete metadata: {len(rows)}/{total}')
    records={};audit=Counter();members=set();ministries=set();years=Counter();dates=[]
    for raw in rows:
        row,reason=normalize(raw,start,end)
        if not row:audit[reason]+=1;continue
        if row['question_id'] in records:audit['duplicate_ids']+=1;continue
        records[row['question_id']]=row;members.update(row['mp_names']);ministries.update(filter(None,row['ministry'].split('; ')))
        dates.append(row['date']);years[row['date'][:4]]+=1
    if audit['duplicate_ids']:raise RuntimeError('Source pagination repeated IDs; publication stopped to avoid silently missing records.')
    stage=root/(uuid.uuid4().hex+'.db');db=sqlite3.connect(stage)
    db.execute('CREATE TABLE records(question_id TEXT PRIMARY KEY,session_no INTEGER,date TEXT,subject TEXT,category TEXT,members TEXT,ministry TEXT,record TEXT)')
    db.executemany('INSERT INTO records VALUES(?,?,?,?,?,?,?,?)',[(r['question_id'],r['session_no'],r['date'],r['subject'],r['debate_category'],json.dumps(r['mp_names']),r['ministry'],json.dumps(r)) for r in records.values()])
    db.execute("CREATE VIRTUAL TABLE docs USING fts5(subject,category,members,ministry,content='records',content_rowid='rowid',tokenize='unicode61')")
    db.execute("INSERT INTO docs(docs) VALUES('rebuild')");db.commit();assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok';db.close();stage.replace(root/'debates.db')
    manifest=dict(status='ready',source='Official Lok Sabha Part-II eLibrary',source_url='https://sansad.in/ls/debates/digitized',
        metadata_endpoint=API,collection=SCOPE,requested_year_from=start,requested_year_to=end,reported_rows=total,
        records=len(records),date_from=min(dates),date_to=max(dates),years=dict(sorted(years.items())),audit=dict(audit),
        members=sorted(members),ministries=sorted(ministries),imported_at=datetime.now(timezone.utc).isoformat())
    pending=root/'manifest.pending';pending.write_text(json.dumps(manifest),encoding='utf-8');pending.replace(root/'manifest.json')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('members','ministries')},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output');p.add_argument('--from-year',type=int,default=2009);p.add_argument('--to-year',type=int,default=2026)
    a=p.parse_args();run(a.output,a.from_year,a.to_year)
