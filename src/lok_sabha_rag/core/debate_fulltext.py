"""Incremental, persistent FTS5 index of verified extracted debate documents."""
import json
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime,timezone
from lok_sabha_rag.config import DATA_DIR
from lok_sabha_rag.core.kaggle_store import split_text,STOP

_lock=threading.Lock()


def root():return DATA_DIR/'debate_fulltext'


def connect():
    root().mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root()/'index.db',timeout=30)
    with _lock:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS documents(question_id TEXT PRIMARY KEY,house TEXT,lok_no INTEGER,session_no INTEGER,date TEXT,ministry TEXT,members TEXT,record TEXT,text TEXT,chunk_count INTEGER,status TEXT,updated_at TEXT)')
        db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(text,question_id UNINDEXED,chunk_index UNINDEXED)')
    return db


def save(row,data):
    text=data.get('text','') if data.get('status')=='extracted' else ''
    parts=list(split_text(text)) if text else []
    with closing(connect()) as db,db:
        db.execute('DELETE FROM passages WHERE question_id=?',(row['question_id'],))
        db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(
            row['question_id'],row['house'],row.get('lok_no'),row.get('session_no'),row['date'],row.get('ministry',''),
            json.dumps(row.get('mp_names',[])),json.dumps(row),text,len(parts),data.get('status','unavailable'),datetime.now(timezone.utc).isoformat()))
        db.executemany('INSERT INTO passages(text,question_id,chunk_index) VALUES(?,?,?)',[(text,row['question_id'],i) for i,text in enumerate(parts)])


def get(qid):
    if not (root()/'index.db').exists():return None
    with closing(connect()) as db:row=db.execute('SELECT record,text,chunk_count,status FROM documents WHERE question_id=?',(qid,)).fetchone()
    if not row:return None
    return {'record':json.loads(row[0]),'text':row[1],'chunk_count':row[2],'status':row[3]}


def search(query,limit=10,house='both',lok=None,session=None,ministry=None,mp_names=None):
    if not (root()/'index.db').exists():return []
    terms=list(dict.fromkeys(t.casefold() for t in re.findall(r'\w+',query) if t.casefold() not in STOP))[:24]
    if not terms:return []
    clauses=['passages MATCH ?','d.status="extracted"'];args=[' OR '.join('"'+t+'"' for t in terms)]
    if house!='both':clauses.append('d.house=?');args.append(house)
    if lok is not None:clauses.append('d.lok_no=?');args.append(lok)
    if session is not None:clauses.append('d.session_no=?');args.append(session)
    if ministry:clauses.append('d.ministry LIKE ?');args.append('%'+ministry+'%')
    if mp_names:
        clauses.append('EXISTS (SELECT 1 FROM json_each(d.members) WHERE value IN ('+','.join('?' for _ in mp_names)+'))');args.extend(mp_names)
    sql='SELECT d.record,passages.text,passages.chunk_index,d.chunk_count FROM passages JOIN documents d ON d.question_id=passages.question_id WHERE '+' AND '.join(clauses)+' ORDER BY bm25(passages),d.date DESC LIMIT ?'
    with closing(connect()) as db:rows=db.execute(sql,args+[min(limit*4,800)]).fetchall()
    result=[];seen=set()
    for raw,text,index,count in rows:
        row=json.loads(raw)
        if row['question_id'] in seen:continue
        seen.add(row['question_id']);row.update(_matched_text=text,_matched_chunk_index=int(index),_total_chunks=count,_fulltext=True);result.append(row)
        if len(result)>=limit:break
    return result


def coverage():
    counts={}
    if (root()/'index.db').exists():
        with closing(connect()) as db:
            for house,status,n,ch,first,last in db.execute('SELECT house,status,count(*),sum(chunk_count),min(date),max(date) FROM documents GROUP BY house,status'):
                item=counts.setdefault(house,{'indexed':0,'attempted':0,'chunks':0,'failures':{}})
                item['attempted']+=n
                if status=='extracted':
                    item['indexed']+=n;item['chunks']+=ch
                    item['date_from']=first;item['date_to']=last
                else:item['failures'][status]=n
    try:job=json.loads((root()/'progress.json').read_text())
    except (OSError,ValueError):job={}
    if job.get('status')=='running':
        try:
            cmd=open(f'/proc/{int(job["pid"])}/cmdline','rb').read()
            if b'index_debates' not in cmd:job['status']='interrupted'
        except (OSError,ValueError,KeyError):job['status']='interrupted'
    return {'houses':counts,'job':job,'checked_at':datetime.now(timezone.utc).isoformat(),
            'method':'Keyword search across indexed speech text; no OCR. Coverage grows as documents are processed.'}
