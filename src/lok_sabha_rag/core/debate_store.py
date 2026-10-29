"""Official Part-2 catalogue retrieval and bounded on-demand PDF extraction."""
import hashlib
import io
import json
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime,timezone
from urllib.parse import urlparse,parse_qs
from urllib.request import Request,urlopen
from lok_sabha_rag.config import DATA_DIR
from lok_sabha_rag.core.kaggle_store import STOP,split_text
from lok_sabha_rag.core import debate_fulltext,ls_debate_documents

_downloads=threading.BoundedSemaphore(4)

def path():return DATA_DIR/'rs_debates'/'debates.db'


def ls_path():return DATA_DIR/'ls_debates'/'debates.db'

def manifest(house='rajya_sabha'):
    try:return json.loads((ls_path() if house=='lok_sabha' else path()).with_name('manifest.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}

def safe_url(url):
    if ls_debate_documents.safe_url(url):return True
    try:
        p=urlparse(str(url or ''))
        prefixes={'bucketapi.rajyasabha.digital':'/public-bucket/rsdebate/assetstore/',
                  'cms.rajyasabha.nic.in':'/UploadedFiles/Debates/','sansad.in':'/getFile/'}
        return p.scheme=='https' and p.port in (None,443) and not p.username and not p.password and p.hostname in prefixes and p.path.startswith(prefixes[p.hostname])
    except ValueError:return False

def connection():return sqlite3.connect(path().resolve().as_uri()+'?mode=ro',uri=True)

def get_record(qid):
    dbpath=ls_path() if str(qid).startswith('LS_D_') else path()
    if not dbpath.exists():return None
    with closing(sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True)) as db:row=db.execute('SELECT record FROM records WHERE question_id=?',(qid,)).fetchone()
    return json.loads(row[0]) if row else None

def metadata_search(query,limit=10,session=None,ministry=None,mp_names=None,dbpath=None,lok=None):
    dbpath=dbpath or path()
    if not dbpath.exists():return []
    terms=list(dict.fromkeys(x.casefold() for x in re.findall(r'\w+',query) if x.casefold() not in STOP))[:24]
    if not terms:return []
    clauses=['docs MATCH ?'];args=[' OR '.join('"'+t+'"' for t in terms)]
    if session is not None:clauses.append('r.session_no=?');args.append(session)
    if lok is not None:clauses.append("json_extract(r.record,'$.lok_no')=?");args.append(lok)
    if ministry:clauses.append('r.ministry LIKE ?');args.append('%'+ministry+'%')
    if mp_names:
        clauses.append('EXISTS (SELECT 1 FROM json_each(r.members) WHERE value IN ('+','.join('?' for _ in mp_names)+'))');args.extend(mp_names)
    sql='SELECT r.record FROM docs JOIN records r ON docs.rowid=r.rowid WHERE '+' AND '.join(clauses)+' ORDER BY bm25(docs,6.0,2.0,1.0,1.0),r.date DESC,r.question_id LIMIT ?'
    with closing(sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True)) as db:rows=db.execute(sql,args+[limit]).fetchall()
    return [json.loads(x[0]) for x in rows]


def search(query,limit=10,session=None,ministry=None,mp_names=None,house='rajya_sabha',lok=None):
    full=debate_fulltext.search(query,limit,house,lok,session,ministry,mp_names)
    ranked=[full]
    if house!='lok_sabha' and lok is None:ranked.append(metadata_search(query,limit,session,ministry,mp_names))
    if house!='rajya_sabha':ranked.append(metadata_search(query,limit,session,ministry,mp_names,ls_path(),lok))
    scores={};records={}
    for rows in ranked:
        for rank,row in enumerate(rows,1):
            qid=row['question_id'];scores[qid]=scores.get(qid,0)+1/(60+rank)
            if qid not in records or row.get('_fulltext'):records[qid]=row
    return [records[qid] for qid in sorted(scores,key=lambda k:-scores[k])[:limit]]

def metadata_text(row):
    return ('[CATALOGUE METADATA ONLY — not a transcript or evidence of statements made]\n'
        f"Title: {row['subject']}\nCategory: {row['debate_category']}\nDate: {row['date']}\n"
        f"Session: {row['session_no']}\nParticipants listed by archive: {', '.join(row['mp_names'])}\n"
        'Open the original PDF or load the transcript before making substantive claims. Participation does not establish a vote or political stance.')


def bound_rs_text(row,data):
    """One archive PDF page may contain adjacent speeches. Bound by actual titles."""
    if data.get('scope_version')==2:return data
    text=data.get('raw_text',data.get('text',''))
    def pattern(title):return r'\s+'.join(re.escape(t) for t in title.split())
    own=re.search(pattern(row['subject']),text,re.IGNORECASE)
    if not own:return {'status':'scope_unverified','text':metadata_text(row)+'\nThe selected debate heading could not be located reliably inside the PDF.','scope_version':2}
    end=len(text)
    with closing(connection()) as db:
        titles=[r[0] for r in db.execute('SELECT subject FROM records WHERE date=? AND question_id!=?',(row['date'],row['question_id']))]
    for title in titles:
        if not title or title.casefold()==row['subject'].casefold():continue
        match=re.search(pattern(title),text[own.end():],re.IGNORECASE)
        if match:end=min(end,own.end()+match.start())
    return {**data,'raw_text':text,'text':text[own.start():end].strip(),'scope_version':2,'text_scope':'Bounded by the selected debate heading and the next known catalogue heading.'}

def transcript(row):
    is_ls=row.get('house')=='lok_sabha'
    folder=(ls_path() if is_ls else path()).parent/'transcripts';cache=folder/(row['question_id']+'.json')
    def register(data):
        if not is_ls and data.get('status')=='extracted':data=bound_rs_text(row,data)
        if data.get('status')=='extracted':
            if data.get('source_pdf_url'):row['source_pdf_url']=data['source_pdf_url']
            row['_text_scope_version']=data.get('scope_version',1)
            old=debate_fulltext.get(row['question_id'])
            if not old or old['record'].get('_text_scope_version')!=row['_text_scope_version']:debate_fulltext.save(row,data)
        elif data.get('scope_version')==2:debate_fulltext.save(row,data)
        return data
    try:
        data=json.loads(cache.read_text(encoding='utf-8'))
        if (is_ls and ls_debate_documents.safe_url(data.get('source_pdf_url'))) or data.get('source_pdf_url')==row['source_pdf_url']:return register(data)
    except (OSError,ValueError):pass
    if is_ls:
        try:
            data=ls_debate_documents.extract(row)
            if data['status']!='extracted':return {'status':data['status'],'text':metadata_text(row)+'\nOriginal PDF text is not available for retrieval.'}
            folder.mkdir(parents=True,exist_ok=True)
            import uuid
            temp=cache.with_name(cache.stem+'-'+uuid.uuid4().hex+'.pending');temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temp.replace(cache)
            return register(data)
        except Exception:return {'status':'unavailable','text':metadata_text(row)+'\nOfficial PDF lookup is temporarily unavailable.'}
    url=row['source_pdf_url']
    if not safe_url(url):return {'status':'unavailable','text':metadata_text(row)}
    try:
        with _downloads:
            with urlopen(Request(url,headers={'User-Agent':'SansadAI/1.0'}),timeout=20) as response:
                if not safe_url(response.url):raise ValueError('Unexpected archive redirect')
                raw=response.read(20_000_001)
            if len(raw)>20_000_000 or not raw.startswith(b'%PDF-'):raise ValueError('Invalid PDF content')
            from lok_sabha_rag.core.bill_documents import extract_pdf
            parsed=extract_pdf(raw)
            if parsed.get('error'):raise ValueError('PDF extraction failed')
            text='\n\n'.join(page['text'] for page in parsed['pages'] if page['readable'])
        if len(text.strip())<100 or text.count('\ufffd')>max(5,len(text)//30):
            return {'status':'pdf_only','text':metadata_text(row)+'\nTranscript text could not be extracted reliably; PDF viewing remains available.'}
        filename=parse_qs(urlparse(url).query).get('response-content-disposition',[''])[0]
        expected=datetime.strptime(row['date'],'%Y-%m-%d').strftime('%d%m%Y')
        # Where an archive filename encodes a session/date, reject disagreement.
        identity=re.search(r'ID_(\d+)_(\d{8})_',filename)
        if identity and (int(identity[1])!=row['session_no'] or identity[2]!=expected):
            return {'status':'identity_mismatch','text':metadata_text(row)+'\nArchive PDF filename disagrees with the catalogue date/session.'}
        data={'status':'extracted','text':text,'source_pdf_url':url,'pdf_sha256':hashlib.sha256(raw).hexdigest(),
              'pages':len(parsed['pages']),'extracted_at':datetime.now(timezone.utc).isoformat()}
        folder.mkdir(parents=True,exist_ok=True)
        # Different requests may extract the same item; use unique staging names.
        import uuid
        temp=cache.with_name(cache.stem+'-'+uuid.uuid4().hex+'.pending')
        temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temp.replace(cache)
        return register(data)
    except Exception:
        return {'status':'unavailable','text':metadata_text(row)+'\nTranscript lookup is temporarily unavailable; do not infer its contents.'}

def payload(row,index=0,text=None,status='metadata_only'):
    if row.get('_fulltext') and text is None:
        text=row['_matched_text'];index=row['_matched_chunk_index'];status='indexed_text'
    return {**row,'text':text if text is not None else metadata_text(row),
            'chunk_id':row['question_id']+':'+str(index),'transcript_status':status,
            'source':{'chunk_index':index,'pdf_url':row['source_pdf_url'],'source_url':row['source_url']}}
