"""On-demand original-document verification for already indexed RS records."""
import hashlib
import json
import threading
from datetime import datetime,timezone
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import URLError
from pathlib import Path
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from lok_sabha_rag.config import DATA_DIR
from lok_sabha_rag.core import kaggle_store
from lok_sabha_rag.core.pdf_links import mapping,verified_document
from lok_sabha_rag.core.pdf_matching import candidate,safe_document,verify_bytes

router=APIRouter();_write_lock=threading.Lock();_remote_limit=threading.BoundedSemaphore(2)

class DocumentRequest(BaseModel):
    question_id:str=Field(min_length=4,max_length=100,pattern=r'^RS_[A-Za-z0-9_]+$')

def find_record(qid):
    if qid.startswith('RS_K_'):return kaggle_store.get_record(qid)
    path=DATA_DIR/'rajya_sabha_hf'/'records.jsonl'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            row=json.loads(line)
            if row['question_id']==qid:return row
    return None

def store_result(qid,entry,reason=None):
    with _write_lock:
        data=dict(mapping());data['links']=dict(data.get('links',{}));data['unmatched']=dict(data.get('unmatched',{}))
        if entry:data['links'][qid]=entry;data['unmatched'].pop(qid,None)
        else:data['unmatched'][qid]={'reason':reason,'checked_at':datetime.now(timezone.utc).isoformat()}
        data['verified_records']=len(data['links']);data['generated_at']=datetime.now(timezone.utc).isoformat()
        path=DATA_DIR/'rajya_sabha'/'pdf-links.json';temp=path.with_suffix('.pending')
        temp.write_text(json.dumps(data,indent=2),encoding='utf-8');temp.replace(path)

@router.post('/rs-document')
def resolve(req:DocumentRequest):
    row=find_record(req.question_id)
    if not row:raise HTTPException(404,'Question is not in the indexed Rajya Sabha corpus.')
    data=mapping();cached=data.get('links',{}).get(req.question_id)
    bound={**row,'source':{'dataset':row.get('source_dataset','anudit/rajyasabha-qa'),'dataset_revision':row.get('dataset_revision',data.get('dataset_revision'))}}
    if cached and verified_document(bound):return {'status':'verified','url':cached['url'],'format':cached.get('format','pdf')}
    failed=data.get('unmatched',{}).get(req.question_id)
    if isinstance(failed,dict):
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(failed['checked_at'])).total_seconds()
            if age<21600:return {'status':'unavailable','message':'No verified original document match. Dataset source remains available.'}
        except (KeyError,ValueError):pass
    if not _remote_limit.acquire(blocking=False):raise HTTPException(429,'Document checks are busy. Please try again shortly.')
    try:
        # These values come only from an indexed record; clients cannot submit URLs or SQL.
        session=int(row['session_no']);number=int(row['ques_no']);kind=row['type'].strip().upper()
        if kind not in ('STARRED','UNSTARRED'):raise ValueError('Unsupported type')
        where=f"ses_no={session} and qno='{number}' and qtype='{kind}'"
        url='https://rsdoc.nic.in/Question/Search_Questions?'+urlencode({'whereclause':where})
        with urlopen(Request(url,headers={'User-Agent':'SansadAI/1.0'}),timeout=15) as response:
            raw=response.read(5_000_001)
        if len(raw)>5_000_000:raise ValueError('Metadata response too large')
        rows=json.loads(raw)
        if not isinstance(rows,list):raise ValueError('Unexpected source format')
        urls={value for item in rows if (value:=candidate(row,item))}
        if len(urls)!=1:raise ValueError('No unique supported original document')
        url=next(iter(urls))
        with urlopen(Request(url,headers={'User-Agent':'SansadAI/1.0'}),timeout=15) as response:
            if not safe_document(response.url,session):raise ValueError('Unexpected document redirect')
            body=response.read(12_000_001)
        valid,kind=verify_bytes(body,url,row)
        if not valid:raise ValueError('Document identity not confirmed')
        entry=dict(url=url,verified=True,format=kind,session_no=session,ques_no=number,type=row['type'],date=row['date'],
            title=row['subject'],source_record_id=row['source_record_id'],
            dataset=row.get('source_dataset','anudit/rajyasabha-qa'),
            dataset_revision=row.get('dataset_revision',data.get('dataset_revision')),
            pdf_sha256=hashlib.sha256(body).hexdigest(),verified_at=datetime.now(timezone.utc).isoformat())
        store_result(req.question_id,entry)
        return {'status':'verified','url':url,'format':kind}
    except (URLError,TimeoutError):
        raise HTTPException(503,'Official source is temporarily unavailable. Please retry later.')
    except Exception:
        store_result(req.question_id,None,'No reliable supported document match')
        return {'status':'unavailable','message':'No verified original document match. Dataset source remains available.'}
    finally:_remote_limit.release()
