"""Read-only full-text retrieval for the deduplicated historical RS corpus."""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from lok_sabha_rag.config import DATA_DIR

DATASET='rajanand/rajyasabha'
REVISION='kaggle-version-4'

def canonical(row):
    # Different dates are distinct parliamentary events, even if text repeats.
    return '|'.join(str(x).strip().upper() for x in ('rajya_sabha',str(row.get('date',''))[:10],row.get('type',''),int(row.get('ques_no') or 0)))

def stable_id(row):
    return 'RS_K_'+hashlib.sha256(canonical(row).encode()).hexdigest()[:24]

def path():return DATA_DIR/'rajya_sabha_kaggle'/'records.db'

def manifest():
    try:return json.loads(path().with_name('manifest.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}

def connect():
    return sqlite3.connect(path().resolve().as_uri()+'?mode=ro',uri=True)

def get_record(question_id):
    if not path().exists():return None
    with closing(connect()) as db:
        row=db.execute('SELECT record FROM records WHERE question_id=?',(question_id,)).fetchone()
    return json.loads(row[0]) if row else None

def split_text(text,size=1400,overlap=180):
    start=0
    while start<len(text):
        end=min(start+size,len(text));yield text[start:end]
        if end==len(text):break
        start=end-overlap

def payload(record,index=0,text=None):
    return {**record,'text':text if text is not None else next(split_text(record['text'])),
        'chunk_id':record['question_id']+':'+str(index),
        'source':{'chunk_index':index,'pdf_url':None,
            'source_url':'https://www.kaggle.com/datasets/rajanand/rajyasabha',
            'dataset':DATASET,'dataset_revision':REVISION,'source_record_id':record['source_record_id']}}

STOP={'what','which','when','where','how','the','a','an','of','in','on','to','and','or','is','are','was','were','has','have','for','from','about','me','tell','please','give','details','regarding'}

def search(query,limit=10,session=None,ministry=None,mp_names=None,record_year=None,record_dates=None):
    if not path().exists():return []
    terms=list(dict.fromkeys(x.casefold() for x in re.findall(r'\w+',query) if x.casefold() not in STOP))[:24]
    if not terms:return []
    match=' OR '.join('"'+x.replace('"','""')+'"' for x in terms)
    filters=['docs MATCH ?'];args=[match]
    if record_dates:
        filters.append("json_extract(r.record,'$.date') IN ("+','.join('?' for _ in record_dates)+')')
        args.extend(record_dates)
    if record_year is not None:
        if not isinstance(record_year,int) or not 1950<=record_year<=2100:raise ValueError('Unsupported calendar year')
        filters.append("json_extract(r.record,'$.date') >= ? AND json_extract(r.record,'$.date') < ?")
        args.extend([f'{record_year}-01-01',f'{record_year+1}-01-01'])
    if session is not None:filters.append('r.session_no=?');args.append(session)
    if ministry:filters.append('r.ministry=? COLLATE NOCASE');args.append(ministry)
    if mp_names:
        filters.append('EXISTS (SELECT 1 FROM json_each(r.members) WHERE value IN ('+','.join('?' for _ in mp_names)+'))');args.extend(mp_names)
    sql='SELECT r.record,bm25(docs,5.0,1.0) AS score FROM docs JOIN records r ON r.rowid=docs.rowid WHERE '+' AND '.join(filters)+' ORDER BY score,r.question_id LIMIT ?'
    args.append(limit)
    with closing(connect()) as db:rows=db.execute(sql,args).fetchall()
    return [json.loads(row[0]) for row in rows]
