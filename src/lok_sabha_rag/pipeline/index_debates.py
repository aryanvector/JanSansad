"""Resumable background extraction; no language-model calls or paid embeddings."""
import argparse
import json
import os
import shutil
import sqlite3
import time
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from contextlib import closing
from lok_sabha_rag.core import debate_store,debate_fulltext


def run(limit=0,retry_failed=False):
    root=debate_fulltext.root();root.mkdir(parents=True,exist_ok=True)
    lock=open(root/'worker.lock','w')
    import fcntl
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('An index worker is already running.')
    started=datetime.now(timezone.utc).isoformat()
    with closing(debate_fulltext.connect()) as db:processed=dict(db.execute('SELECT question_id,status FROM documents'))
    rows={}
    for house,path in [('lok_sabha',debate_store.ls_path()),('rajya_sabha',debate_store.path())]:
        if not path.exists():continue
        with closing(sqlite3.connect(path)) as db:
            rows[house]=[json.loads(r[0]) for r in db.execute('SELECT record FROM records ORDER BY date DESC,question_id')]
    # Interleave the two Houses, newest first within each House.
    work=[];houses=list(rows)
    for i in range(max((len(r) for r in rows.values()),default=0)):
        for house in houses:
            if i<len(rows[house]):
                row=rows[house][i];old=processed.get(row['question_id'])
                if old is None or retry_failed and old!='extracted':work.append(row)
    if limit:work=work[:limit]
    progress={'pid':os.getpid(),'status':'running','started_at':started,'queued':len(work),'completed':0,'extracted':0,'failed':0,'last_record':None}
    def publish():
        progress['updated_at']=datetime.now(timezone.utc).isoformat()
        temp=root/'progress.pending';temp.write_text(json.dumps(progress),encoding='utf-8');temp.replace(root/'progress.json')
    publish()
    def index(row):
        try:data=debate_store.transcript(row)
        except Exception:data={'status':'unavailable','text':''}
        if data['status']!='extracted':debate_fulltext.save(row,data)
        time.sleep(.15)
        return row,data['status']
    with ThreadPoolExecutor(max_workers=2) as pool:
        # Keep the queue bounded so stop requests don't leave thousands of futures.
        for offset in range(0,len(work),2):
            if (root/'STOP').exists():progress['status']='stopped';break
            if shutil.disk_usage(root).free<2_000_000_000:progress['status']='disk_space_limit';break
            for row,status in pool.map(index,work[offset:offset+2]):
                progress['completed']+=1;progress['extracted' if status=='extracted' else 'failed']+=1
                progress['last_record']=row['question_id'];publish()
                if progress['completed']%20==0:print(json.dumps(progress),flush=True)
        else:progress['status']='complete'
    publish();print(json.dumps(progress),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=0);p.add_argument('--retry-failed',action='store_true');p.add_argument('--log-file')
    args=p.parse_args()
    if args.log_file:
        log=open(args.log_file,'a',buffering=1);sys.stdout=log;sys.stderr=log
    run(args.limit,args.retry_failed)
