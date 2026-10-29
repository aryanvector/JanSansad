"""Audit all supplied CSVs and build a deduplicated, atomic FTS5 catalogue."""
import csv
import hashlib
import html
import io
import json
import re
import sqlite3
import sys
import uuid
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from lok_sabha_rag.core.kaggle_store import canonical,stable_id,DATASET,REVISION

def decode(raw):
    for enc in ('utf-8-sig','cp1252','latin-1'):
        try:return raw.decode(enc),enc
        except UnicodeDecodeError:pass

def clean(value):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]*>',' ',value or ''))).strip()

def build(source,output,hf_records):
    csv.field_size_limit(20_000_000)
    source=Path(source);out=Path(output);out.mkdir(parents=True,exist_ok=True)
    with (source/'rajyasabha_session.csv').open(encoding='utf-8-sig') as source_sessions:
        sessions=list(csv.DictReader(source_sessions))
    hf=[json.loads(x) for x in Path(hf_records).read_text(encoding='utf-8').splitlines()]
    hf_keys={canonical(x) for x in hf}
    temp=out/f'records.building-{uuid.uuid4().hex}.db'
    db=sqlite3.connect(temp)
    db.execute('CREATE TABLE records(question_id TEXT PRIMARY KEY,canonical TEXT UNIQUE,session_no INTEGER,ministry TEXT,members TEXT,subject TEXT,text TEXT,record TEXT)')
    counts=Counter();members=set();ministries=set();dates=[];files=[];conflicts=[]
    for file in sorted(source.glob('rajyasabha_questions_and_answers_*.csv')):
        raw=file.read_bytes();text,encoding=decode(raw)
        files.append({'file':file.name,'sha256':hashlib.sha256(raw).hexdigest(),'encoding':encoding})
        for row in csv.DictReader(io.StringIO(text)):
            counts['input_rows']+=1
            try:
                date=datetime.strptime(row['answer_date'].strip(),'%d.%m.%Y').date().isoformat()
                number=int(row['question_no']);kind=row['question_type'].strip().upper()
                if kind not in ('STARRED','UNSTARRED'):raise ValueError('Unknown question type')
                session=next((int(x['session_no']) for x in sessions if x['session_start_date']<=date<=x['session_end_date']),None)
                if session is None:raise ValueError('No session calendar match')
            except (ValueError,TypeError,KeyError):counts['invalid_metadata']+=1;continue
            if len((row.get('answer') or '').strip())<30:counts['missing_short_answers']+=1;continue
            record=dict(house='rajya_sabha',lok_no=None,session_no=session,ques_no=number,type=kind,date=date,
                subject=clean(row.get('question_title')),ministry=clean(row.get('ministry')),
                mp_names=[clean(row.get('question_by'))],source_record_id=int(row.get('id') or row['question']),
                source_dataset=DATASET,dataset_revision=REVISION,source_file=file.name,
                text=f"RAJYA SABHA\n{kind} QUESTION NO. {number}\nANSWERED ON {date}\n{clean(row.get('question_title'))}\n{clean(row.get('question_description'))}\nANSWER\n{clean(row.get('answer'))}")
            key=canonical(record)
            if key in hf_keys:counts['overlap_with_active_hf']+=1;continue
            record['question_id']=stable_id(record)
            old=db.execute('SELECT record FROM records WHERE canonical=?',(key,)).fetchone()
            if old:
                counts['duplicate_rows']+=1;previous=json.loads(old[0])
                merged=sorted(set(previous['mp_names']+record['mp_names']))
                if previous['text']!=record['text']:counts['duplicate_content_variants']+=1;conflicts.append(key)
                # Prefer the more complete version; preserve all questioner names.
                if len(previous['text'])>=len(record['text']):record=previous
                record['mp_names']=merged
            members.update(record['mp_names']);ministries.add(record['ministry']);dates.append(date)
            db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?,?)',
                (record['question_id'],key,session,record['ministry'],json.dumps(record['mp_names']),record['subject'],record['text'],json.dumps(record,ensure_ascii=False)))
        print(f"Audited {file.name}",flush=True)
    db.execute("CREATE VIRTUAL TABLE docs USING fts5(subject,text,content='records',content_rowid='rowid',tokenize='unicode61')")
    db.execute("INSERT INTO docs(docs) VALUES('rebuild')")
    db.execute('CREATE INDEX session_idx ON records(session_no)')
    db.commit()
    count=db.execute('SELECT count(*) FROM records').fetchone()[0]
    assert count==db.execute('SELECT count(DISTINCT canonical) FROM records').fetchone()[0]
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    latest=[json.loads(r[0]) for r in db.execute('SELECT record FROM records ORDER BY json_extract(record,\'$.date\') DESC,question_id LIMIT 100')]
    (out/'pdf-seed-records.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in latest),encoding='utf-8')
    db.close();temp.replace(out/'records.db')
    manifest=dict(status='ready',dataset=DATASET,dataset_revision=REVISION,listed_license='CC-BY-SA-4.0',records=count,
        date_from=min(dates),date_to=max(dates),members=sorted(members),ministries=sorted(ministries),
        retrieval_method='SQLite FTS5 keyword search; rank fusion with HF vector search',
        audit=dict(counts),files=files,duplicate_variant_keys=conflicts,
        deduplication='House + answer date + question type + question number; checked against all active HF records',
        imported_at=datetime.now(timezone.utc).isoformat())
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('members','ministries','files','duplicate_variant_keys')},indent=2))

if __name__=='__main__':build(*sys.argv[1:])
