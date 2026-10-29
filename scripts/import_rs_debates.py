"""Import the official Part-2 catalogue for an explicit year range, no Q&A."""
import argparse
import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.parse import urlencode,urlparse
from urllib.request import Request,urlopen

API='https://integration.rajyasabha.digital/rsdebate/api/restv4/fetch/all'
HOSTS={'bucketapi.rajyasabha.digital','cms.rajyasabha.nic.in','sansad.in'}

def safe_url(url):
    try:
        p=urlparse(str(url or ''))
        prefixes={'bucketapi.rajyasabha.digital':'/public-bucket/rsdebate/assetstore/','cms.rajyasabha.nic.in':'/UploadedFiles/Debates/','sansad.in':'/getFile/'}
        return p.scheme=='https' and p.port in (None,443) and p.hostname in prefixes and p.path.startswith(prefixes[p.hostname]) and not p.username and not p.password
    except ValueError:return False

def normalize(row,start,end):
    date=str(row.get('date') or '')[:10]
    try:datetime.strptime(date,'%Y-%m-%d')
    except ValueError:return None,'invalid_date'
    if not f'{start}-01-01'<=date<=f'{end}-12-31':return None,'outside_requested_range'
    if 'other than question' not in str(row.get('type','')).lower() or row.get('questionType') or row.get('questionNo'):
        return None,'qa_excluded'
    files=[x for x in row.get('files',[]) if safe_url(x)]
    if not row.get('resourceId') or not files:return None,'no_safe_document'
    title=re.sub(r'\s+',' ',str(row.get('title') or '')).strip()
    if not title:return None,'missing_title'
    return dict(question_id=f"RS_D_{int(row['resourceId'])}",content_type='debate',house='rajya_sabha',lok_no=None,
        session_no=int(row['sessionNo']),ques_no=None,type='DEBATE',date=date,subject=title,
        debate_category=str(row.get('debateTitleSubject') or '').strip(),
        mp_names=[str(x).strip() for x in row.get('members',[]) if x],
        ministry='; '.join(row.get('ministry') or []),language=row.get('language') or [],
        original_pages=str(row.get('pageNoFromTo') or ''),files=files,
        source_record_id=int(row['resourceId']),source_handle=row.get('handle'),
        source_url='https://sansad.in/rs/debates/officials',source_pdf_url=files[0]),None

def run(output,start=2009,end=2026):
    root=Path(output);root.mkdir(parents=True,exist_ok=True);cache=root/'metadata';cache.mkdir(exist_ok=True)
    size=500
    def fetch(offset):
        dest=cache/f'{start}-{end}-{offset}.json'
        if dest.exists():return json.loads(dest.read_text(encoding='utf-8'))
        url=API+'?'+urlencode(dict(start=offset,rows=size,collectionId=2,year=f'{start}#{end}'))
        with urlopen(Request(url,headers={'User-Agent':'SansadAI/1.0'}),timeout=30) as response:
            raw=response.read(20_000_001)
        if len(raw)>20_000_000:raise ValueError('Metadata page too large')
        data=json.loads(raw)
        if not isinstance(data.get('records'),list):raise ValueError('Unexpected official response')
        dest.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        return data
    first=fetch(0);total=int(first['rowsCount']);pages=[first]
    print(f'Official catalogue reports {total} Part-2 entries in {start}–{end}',flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(fetch,offset) for offset in range(size,total,size)]
        for index,future in enumerate(as_completed(futures),2):
            pages.append(future.result())
            if index%10==0:print(f'Metadata pages fetched: {index}/{(total+size-1)//size}',flush=True)
    # The public API's date-tied pagination can repeat IDs across boundaries.
    # Re-fetch whole sessions (each within its 1000-row cap) to avoid omissions.
    preliminary=[row for page in pages for row in page['records']]
    repeated=len(preliminary)-len({row.get('resourceId') for row in preliminary})
    min_session=min(int(row['sessionNo']) for row in preliminary)
    max_session=max(int(row['sessionNo']) for row in preliminary)
    def session_batch(session):
        dest=cache/f'{start}-{end}-session-{session}.json'
        if dest.exists():data=json.loads(dest.read_text(encoding='utf-8'))
        else:
            url=API+'?'+urlencode(dict(start=0,rows=1000,collectionId=2,year=f'{start}#{end}',sessionNo=f'({session})'))
            with urlopen(Request(url,headers={'User-Agent':'SansadAI/1.0'}),timeout=30) as response:raw=response.read(20_000_001)
            if len(raw)>20_000_000:raise ValueError('Session metadata too large')
            data=json.loads(raw);dest.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        if int(data['rowsCount'])!=len(data['records']):raise RuntimeError(f'Session {session} exceeds one-batch limit or is incomplete')
        return data
    with ThreadPoolExecutor(max_workers=3) as pool:stable=list(pool.map(session_batch,range(min_session,max_session+1)))
    if sum(len(page['records']) for page in stable)!=total:raise RuntimeError('Session batches do not cover the official range total')
    pages=stable
    from collections import Counter
    audit=Counter();records={};keys=set();members=set();ministries=set();dates=[];years=Counter()
    audit['pagination_repeats_avoided']=repeated
    raw_count=0
    for page in pages:
        for row in page['records']:
            raw_count+=1;record,reason=normalize(row,start,end)
            if not record:audit[reason]+=1;continue
            digest=hashlib.sha256(json.dumps([record['date'],record['subject'],record['debate_category'],sorted(record['files'])],ensure_ascii=False).encode()).hexdigest()
            if record['question_id'] in records or digest in keys:audit['duplicate_entries']+=1;continue
            keys.add(digest);records[record['question_id']]=record
            members.update(record['mp_names']);ministries.update(x.strip() for x in record['ministry'].split(';') if x.strip())
            dates.append(record['date']);years[record['date'][:4]]+=1
    if raw_count!=total:raise RuntimeError(f'Pagination incomplete: {raw_count}/{total}')
    if not records:raise RuntimeError('No eligible debate records')
    stage=root/f'debates-{uuid.uuid4().hex}.db';db=sqlite3.connect(stage)
    db.execute('CREATE TABLE records(question_id TEXT PRIMARY KEY,session_no INTEGER,date TEXT,subject TEXT,category TEXT,members TEXT,ministry TEXT,record TEXT)')
    db.executemany('INSERT INTO records VALUES(?,?,?,?,?,?,?,?)',[(r['question_id'],r['session_no'],r['date'],r['subject'],r['debate_category'],json.dumps(r['mp_names']),r['ministry'],json.dumps(r,ensure_ascii=False)) for r in records.values()])
    db.execute("CREATE VIRTUAL TABLE docs USING fts5(subject,category,members,ministry,content='records',content_rowid='rowid',tokenize='unicode61')")
    db.execute("INSERT INTO docs(docs) VALUES('rebuild')");db.commit()
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok';db.close();stage.replace(root/'debates.db')
    manifest=dict(status='ready',source='Official Rajya Sabha debates archive',source_url='https://rsdebate.nic.in/',
        archive_url='https://sansad.in/rs/debates/officials',metadata_endpoint=API,requested_year_from=start,requested_year_to=end,
        reported_rows=total,records=len(records),date_from=min(dates),date_to=max(dates),years=dict(sorted(years.items())),
        audit=dict(audit),members=sorted(members),ministries=sorted(ministries),
        transcript_scope='Catalogue metadata indexed; PDF transcripts extracted and cached on demand. No OCR or automatic member-vote attribution.',
        imported_at=datetime.now(timezone.utc).isoformat())
    temp=root/'manifest.pending';temp.write_text(json.dumps(manifest,indent=2),encoding='utf-8');temp.replace(root/'manifest.json')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('members','ministries')},indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output');p.add_argument('--from-year',type=int,default=2009);p.add_argument('--to-year',type=int,default=2026)
    args=p.parse_args();run(args.output,args.from_year,args.to_year)
