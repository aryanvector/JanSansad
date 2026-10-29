"""Version-isolated PDF ingestion, page retrieval and grounded bill answers."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from lok_sabha_rag.config import DATA_DIR

VERSIONS = {'introduced':'As introduced', 'ls_passed':'As passed by Lok Sabha',
            'rs_passed':'As passed by Rajya Sabha', 'both_passed':'As passed by both Houses',
            'gazette':'Gazette notification'}
EXTRACTOR_VERSION = 1
MAX_BYTES = 20_000_000
_downloads = threading.BoundedSemaphore(2)
_ingest_lock = threading.Lock()
STOP = set('a an the this that these those is are was were be been being do does did what which who how when where why of to for in on at by and or with from as about explain tell me please bill act provisions provision summary summarize summarise main key'.split())


class DocumentError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message); self.status = status


def safe_url(url):
    try:
        p=urlsplit(url)
        return (p.scheme=='https' and p.hostname in ('sansad.in','www.sansad.in') and p.port in (None,443)
                and not p.username and not p.password and p.path.startswith(('/getFile/','/uploads/')))
    except ValueError:return False


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_url(newurl):raise DocumentError('Official document redirected outside the approved archive.',502)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def source(row, version):
    label=VERSIONS.get(version)
    doc=next((d for d in row['documents'] if d['label']==label),None)
    if not doc or not safe_url(doc['url']):raise DocumentError('This bill version has no supported official document link.',404)
    if urlsplit(doc['url']).path.lower().endswith(('.doc','.docx')):
        raise DocumentError('This version is a Word document. Open its official link; PDF question answering is not available for this version.')
    return doc


def versions(row):
    result=[]
    for key,label in VERSIONS.items():
        doc=next((d for d in row['documents'] if d['label']==label and safe_url(d['url'])),None)
        if doc:result.append({'key':key,**doc,'pdf_supported':not urlsplit(doc['url']).path.lower().endswith(('.doc','.docx'))})
    return result


def folder(row,version):
    doc=source(row,version)
    digest=hashlib.sha256(f'{EXTRACTOR_VERSION}|{row["id"]}|{version}|{doc["url"]}'.encode()).hexdigest()
    return DATA_DIR/'bills'/'documents'/digest


def cached(row,version):
    root=folder(row,version)
    try:
        data=json.loads((root/'pages.json').read_text(encoding='utf-8'))
        if data['source_url']==source(row,version)['url'] and (root/'original.pdf').exists():return data
    except (OSError,ValueError,KeyError):pass
    return None


def extract_pdf(raw):
    # Parsing untrusted PDFs in a separate process bounds CPU/memory and wall time.
    try:
        proc=subprocess.run([sys.executable,'-m','lok_sabha_rag.core.bill_documents','--extract'],
                            input=raw,capture_output=True,timeout=45)
        if proc.returncode:raise DocumentError('PDF text extraction failed or exceeded its safety limits. Open the original PDF instead.')
        try:return json.loads(proc.stdout)
        except (ValueError,UnicodeError):raise DocumentError('PDF extraction returned unreadable output. Open the original PDF instead.') from None
    except subprocess.TimeoutExpired:
        raise DocumentError('PDF text extraction exceeded 45 seconds. Open the original PDF instead.') from None


def prepare(row,version):
    previous=cached(row,version)
    if previous:return previous
    # Avoid duplicate work for simultaneous requests. Parsing has its own deadline.
    if not _ingest_lock.acquire(timeout=2):raise DocumentError('Another bill PDF is loading. Please try again shortly.',503)
    try:
        previous=cached(row,version)
        if previous:return previous
        doc=source(row,version);p=urlsplit(doc['url'])
        url=urlunsplit((p.scheme,p.netloc,quote(unquote(p.path),safe='/'),p.query,''))
        try:
            with _downloads,build_opener(OfficialRedirects()).open(Request(url,headers={'User-Agent':'SansadAI/1.0'}),timeout=25) as response:
                if not safe_url(response.url):raise DocumentError('Unexpected document source.',502)
                raw=response.read(MAX_BYTES+1)
        except DocumentError:raise
        except Exception:raise DocumentError('The official PDF could not be downloaded. Please try again or open the source link.',502) from None
        if len(raw)>MAX_BYTES:raise DocumentError('This PDF exceeds the 20 MB document limit.')
        if not raw.startswith(b'%PDF-'):raise DocumentError('The source did not return a PDF. No text was indexed.',502)
        parsed=extract_pdf(raw)
        if parsed.get('error'):raise DocumentError(parsed['error'])
        pages=parsed['pages'];readable=[p for p in pages if p['readable']]
        if not readable:raise DocumentError('No reliable text could be extracted. This PDF may need OCR; use the original document for now.')
        # Verify the title against readable opening pages before attributing its contents.
        terms={t for t in tokens(row['title']) if not t.isdigit()}
        opening=' '.join(p['text'] for p in pages[:3]).casefold()
        matched=sum(t in opening for t in terms)
        if terms and matched/max(1,len(terms))<0.6:
            raise DocumentError('The PDF opening does not match the selected bill title. It was not indexed; inspect the official source.')
        warnings=[]
        if len(readable)!=len(pages):warnings.append(f'{len(pages)-len(readable)} PDF page(s) had insufficient or unreliable text and are excluded from retrieval. No OCR was performed.')
        warnings.append('Version label comes from the official catalogue. PDF page numbers are file positions, which may differ from printed page numbers.')
        data=dict(bill_id=row['id'],title=row['title'],version=version,version_label=doc['label'],source_url=doc['url'],
                  pdf_sha256=hashlib.sha256(raw).hexdigest(),extractor_version=EXTRACTOR_VERSION,
                  extracted_at=datetime.now(timezone.utc).isoformat(),page_count=len(pages),
                  readable_pages=len(readable),warnings=warnings,pages=pages)
        root=folder(row,version);root.mkdir(parents=True,exist_ok=True)
        stage=root/(uuid.uuid4().hex+'.pdf.pending');stage.write_bytes(raw);stage.replace(root/'original.pdf')
        stage=root/(uuid.uuid4().hex+'.json.pending');stage.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');stage.replace(root/'pages.json')
        return data
    finally:_ingest_lock.release()


def tokens(text):return [t.casefold() for t in re.findall(r'\w+',text) if t.casefold() not in STOP and len(t)>1]


def chunks(data):
    items=[]
    for page in data['pages']:
        if not page['readable']:continue
        text=page['text'];start=0
        while start<len(text):
            end=min(start+1800,len(text))
            items.append({'page':page['page'],'text':text[start:end],'offset':start})
            if end==len(text):break
            start=end-240
    return items


def retrieve(data,question,limit=8):
    items=chunks(data)
    if not items:return [],'none'
    query=set(tokens(question));counts=[Counter(tokens(c['text'])) for c in items]
    avg=sum(sum(c.values()) for c in counts)/len(counts) or 1
    df=Counter(t for c in counts for t in query if t in c)
    scored=[]
    for idx,(chunk,count) in enumerate(zip(items,counts)):
        length=sum(count.values());score=0
        for t in query:
            tf=count[t]
            if tf:score+=math.log(1+(len(items)-df[t]+.5)/(df[t]+.5))*tf*2.2/(tf+1.2*(.25+.75*length/avg))
        if score:scored.append((score,idx,chunk))
    if not scored:
        # Overview queries get distributed excerpts, explicitly marked as sampling.
        if query:return [],'no_lexical_match'
        indices=sorted({round(i*(len(items)-1)/max(1,limit-1)) for i in range(min(limit,len(items)))})
        chosen=[items[i] for i in indices];mode='overview_sample'
    else:
        chosen=[v[2] for v in sorted(scored,key=lambda v:(-v[0],v[1]))[:limit]];mode='bm25'
    evidence=[]
    for idx,c in enumerate(chosen,1):
        evidence.append({**c,'citation':f'E{idx}','source_url':data['source_url'],
                         'pdf_url':f'/api/bills/{data["bill_id"]}/pdf?version={data["version"]}#page={c["page"]}'})
    return evidence,mode


def context_for(data,evidence):
    return (f'Selected bill: {data["title"]}\nONLY version: {data["version_label"]}\n'
            f'Source: {data["source_url"]}\nPDF SHA256: {data["pdf_sha256"]}\n'
            'Excerpts are partial; absence from retrieved excerpts is not proof of absence from the bill.\n\n'+
            '\n\n'.join(f'[{e["citation"]}] PDF page {e["page"]}\n{e["text"]}' for e in evidence))


def generate_answer(question,context):
    from lok_sabha_rag.core.ai_provider import generate
    instructions=(Path(__file__).parents[1]/'prompts'/'bill_system.txt').read_text(encoding='utf-8')
    return generate(instructions,f'QUESTION:\n{question}\n\nUNTRUSTED DOCUMENT EXCERPTS:\n{context}',max_tokens=2048,task='bill')


def answer(row,version,question,synthesize=True):
    data=prepare(row,version);evidence,mode=retrieve(data,question)
    result={'bill_id':row['id'],'title':row['title'],'version':version,'version_label':data['version_label'],
            'source_url':data['source_url'],'pdf_sha256':data['pdf_sha256'],'page_count':data['page_count'],
            'readable_pages':data['readable_pages'],'extracted_at':data['extracted_at'],'retrieval_method':mode,
            'warnings':list(data['warnings']),'evidence':evidence,'answer':None,'cited_evidence':[],
            'answer_status':'sources_only','citation_check':'not_run','ai_error':None,'ai_message':None}
    if mode=='overview_sample':result['warnings'].append('Overview uses sampled excerpts, not an exhaustive reading of the entire bill.')
    if not evidence:
        result['answer_status']='insufficient_evidence';result['warnings'].append('No matching passage was found by keyword retrieval. Try words used in the bill; this does not prove the topic is absent.')
        return result
    if not synthesize:return result
    try:text=generate_answer(question,context_for(data,evidence))
    except DocumentError:raise
    except Exception as error:
        from lok_sabha_rag.core.ai_provider import GenerationError
        code=getattr(error,'code',None)
        if isinstance(error,GenerationError):
            result['ai_error']=error.code;message=str(error)
        elif code in ('insufficient_quota','credit_balance_exhausted'):
            result['ai_error']='quota_exhausted'
            message='The configured AI provider reports exhausted API credits. Restore its API billing or credits to enable generated answers. Source retrieval remains available.'
        elif getattr(error,'status_code',None) in (401,403):
            result['ai_error']='authentication_failed'
            message='The AI provider rejected the server credentials or access. Update the server API configuration; do not paste keys into this page.'
        else:
            result['ai_error']='provider_unavailable'
            message='AI generation is unavailable. Check the server API configuration or provider availability; retrieved source passages remain available.'
        result['answer_status']='ai_unavailable';result['ai_message']=message;result['warnings'].append(message)
        return result
    from lok_sabha_rag.core.ai_provider import normalize_citation_groups
    text=normalize_citation_groups(text,'E')
    cited=[int(n) for n in re.findall(r'\[E(\d+)\]',text)]
    malformed=any(not re.fullmatch(r'\[E\d+\]',tag) for tag in re.findall(r'\[E\d[^\]]*\]',text))
    if malformed or not cited or any(n<1 or n>len(evidence) for n in cited):
        result['answer_status']='citation_check_failed';result['warnings'].append('The generated answer had missing or invalid evidence references and was withheld. Inspect the retrieved passages instead.')
        return result
    result.update(answer=text,answer_status='generated',cited_evidence=sorted(set(cited)),citation_check='reference_ids_valid')
    result['warnings'].append('Citation IDs were checked against retrieved passages. This is not automatic proof that every generated claim is supported.')
    return result


def _extract_worker():
    try:
        if sys.platform!='win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024));resource.setrlimit(resource.RLIMIT_CPU,(30,30))
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(sys.stdin.buffer.read(MAX_BYTES+1)))
        if reader.is_encrypted and not reader.decrypt(''):raise ValueError('Encrypted PDF is not supported.')
        if len(reader.pages)>150:raise ValueError('This PDF exceeds the 150-page extraction limit.')
        pages=[];total=0
        for i,page in enumerate(reader.pages,1):
            text=(page.extract_text() or '').replace('\x00','');total+=len(text)
            if total>1_500_000:raise ValueError('Extracted text exceeds the document limit.')
            letters=sum(c.isalpha() for c in text)
            readable=letters>=35 and text.count('\ufffd')<=max(3,len(text)//100)
            pages.append({'page':i,'text':text,'readable':readable})
        print(json.dumps({'pages':pages},ensure_ascii=True))
    except Exception as error:print(json.dumps({'error':str(error)[:200]}))


if __name__=='__main__' and '--extract' in sys.argv:_extract_worker()
