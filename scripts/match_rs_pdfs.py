"""Verify official RS PDF identities before publishing any link. No URL guessing."""
import argparse
import hashlib
import html
import io
import json
import re
import time
from pathlib import Path
from datetime import datetime,timezone
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.parse import urlparse,urlencode
from urllib.request import Request,urlopen
from pypdf import PdfReader

REVISION='508b2411283162fdd52ee2c3e8ccaefbabfe9581'

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from lok_sabha_rag.core.pdf_matching import words,metadata_key,safe_pdf,safe_document,candidate,verify_text,verify_bytes

def fetch_metadata(records_path,official_path):
    records=[json.loads(x) for x in Path(records_path).read_text(encoding='utf-8-sig').splitlines()]
    dates={}
    for row in records:dates.setdefault(int(row['session_no']),[]).append(row['date'])
    merged=[]
    for session,days in dates.items():
        start=datetime.strptime(min(days),'%Y-%m-%d').strftime('%d/%m/%Y')
        end=datetime.strptime(max(days),'%Y-%m-%d').strftime('%d/%m/%Y')
        where=f"ses_no={session} and (CONVERT(datetime, adate, 103) >= CONVERT(datetime, '{start}', 103)) and (CONVERT(datetime, adate, 103) <= CONVERT(datetime, '{end}', 103))"
        url='https://rsdoc.nic.in/Question/Search_Questions?'+urlencode({'whereclause':where})
        with urlopen(Request(url,headers={'User-Agent':'SansadAI/1.0'}),timeout=30) as response:
            raw=response.read(20_000_001)
        if len(raw)>20_000_000:raise ValueError('Official metadata response exceeds size limit')
        rows=json.loads(raw)
        if not isinstance(rows,list):raise ValueError('Unexpected official metadata format')
        merged.extend(rows)
    Path(official_path).write_text(json.dumps(merged,ensure_ascii=False),encoding='utf-8')

def run(records_path,official_path,out_path,dataset='anudit/rajyasabha-qa',revision=REVISION):
    records=[json.loads(x) for x in Path(records_path).read_text(encoding='utf-8-sig').splitlines()]
    official=json.loads(Path(official_path).read_text(encoding='utf-8-sig'))
    lookup={}
    for row in official:
        try:lookup.setdefault(metadata_key(row,True),[]).append(row)
        except (ValueError,TypeError):continue
    folder=Path(out_path).parent/'verified-rs-pdfs';folder.mkdir(exist_ok=True,parents=True)
    def match(record):
        matches=[]
        for row in lookup.get(metadata_key(record),[]):
            url=candidate(record,row)
            if url:matches.append((url,row))
        urls={x[0] for x in matches}
        if len(urls)!=1:return record['question_id'],None,'no_unique_official_match'
        url=next(iter(urls));suffix='.docx' if urlparse(url).path.lower().endswith('.docx') else '.pdf';dest=folder/(record['question_id']+suffix)
        try:
            if dest.exists():data=dest.read_bytes()
            else:
                for attempt in range(2):
                    try:
                        with urlopen(Request(url,headers={'User-Agent':'SansadAI/1.0'}),timeout=18) as response:
                            if not safe_document(response.url,record['session_no']):raise ValueError('Unexpected redirect')
                            data=response.read(12_000_001)
                        break
                    except Exception:
                        if attempt:raise
                        time.sleep(1)
            valid,kind=verify_bytes(data,url,record)
            if not valid:return record['question_id'],None,'document_identity_not_confirmed'
            dest.write_bytes(data)
            return record['question_id'],dict(url=url,verified=True,dataset=dataset,dataset_revision=revision,
                format=kind,
                session_no=record['session_no'],ques_no=record['ques_no'],type=record['type'],date=record['date'],
                title=record['subject'],source_record_id=record['source_record_id'],
                pdf_sha256=hashlib.sha256(data).hexdigest(),verified_at=datetime.now(timezone.utc).isoformat()),None
        except Exception as exc:return record['question_id'],None,type(exc).__name__
    links={};unmatched={}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(match,r) for r in records]
        for n,future in enumerate(as_completed(futures),1):
            qid,link,reason=future.result()
            if link:links[qid]=link
            else:unmatched[qid]=reason
            if n%50==0 or n==len(records):print(f'Checked {n}/{len(records)}; verified {len(links)}',flush=True)
    manifest=dict(dataset=dataset,dataset_revision=revision,
        records_checked=len(records),verified_records=len(links),links=links,unmatched=unmatched,
        official_search_url='https://sansad.in/rs/questions/questions-and-answers',
        metadata_endpoint='https://rsdoc.nic.in/Question/Search_Questions',
        metadata_sha256=hashlib.sha256(Path(official_path).read_bytes()).hexdigest(),
        generated_at=datetime.now(timezone.utc).isoformat())
    Path(out_path).write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('links','unmatched')},indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('records');p.add_argument('official');p.add_argument('output')
    p.add_argument('--refresh-metadata',action='store_true')
    p.add_argument('--dataset',default='anudit/rajyasabha-qa');p.add_argument('--revision',default=REVISION)
    a=p.parse_args()
    if a.refresh_metadata:fetch_metadata(a.records,a.official)
    run(a.records,a.official,a.output,a.dataset,a.revision)
