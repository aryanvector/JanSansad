"""Resolve original Lok Sabha eLibrary PDFs via official DSpace bundles."""
import hashlib
import json
from datetime import datetime,timezone
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urlparse
from lok_sabha_rag.core import bill_documents


def safe_url(url):
    try:
        p=urlparse(str(url or ''))
        return (p.scheme=='https' and p.hostname=='elibrary.sansad.in' and p.port in (None,443)
                and not p.username and not p.password and p.path.startswith('/server/api/core/'))
    except ValueError:return False


class Redirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not safe_url(newurl):raise ValueError('Unexpected archive redirect')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def download(url,limit):
    if not safe_url(url):raise ValueError('Unapproved library URL')
    with build_opener(Redirects()).open(Request(url,headers={'User-Agent':'SansadAI/1.0'}),timeout=20) as response:raw=response.read(limit+1)
    if len(raw)>limit:raise ValueError('Archive response exceeds limit')
    return raw


def extract(row):
    bundles=json.loads(download(row['bundles_url'],2_000_000)).get('_embedded',{}).get('bundles',[])
    bundle=next((b for b in bundles if b.get('name')=='ORIGINAL'),None)
    if not bundle:return {'status':'no_original_pdf','text':''}
    streams=json.loads(download(bundle['_links']['bitstreams']['href'],2_000_000)).get('_embedded',{}).get('bitstreams',[])
    pdfs=[s for s in streams if str(s.get('name','')).lower().endswith('.pdf')]
    if not pdfs:return {'status':'no_original_pdf','text':''}
    # Keep one specific original PDF. Parse it directly rather than assume that a
    # separate TEXT bundle necessarily corresponds to this PDF/language version.
    selected=sorted(pdfs,key=lambda s:('eng' not in s.get('name','').lower(),s.get('name','')))[0]
    url=selected['_links']['content']['href'];raw=download(url,20_000_000)
    if not raw.startswith(b'%PDF-'):return {'status':'invalid_pdf','text':''}
    parsed=bill_documents.extract_pdf(raw)
    if parsed.get('error'):return {'status':'pdf_only','text':''}
    pages=parsed['pages'];text='\n\n'.join(p['text'] for p in pages if p['readable'])
    if len(text.strip())<100:return {'status':'pdf_only','text':''}
    row['source_pdf_url']=url;row['files']=[url]
    return {'status':'extracted','text':text,'source_pdf_url':url,'pdf_sha256':hashlib.sha256(raw).hexdigest(),
            'pages':len(pages),'extracted_at':datetime.now(timezone.utc).isoformat()}
