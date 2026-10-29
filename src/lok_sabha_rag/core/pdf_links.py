"""Read-only, revision-bound PDF mappings. Search never performs remote lookups."""
import json
from functools import lru_cache
from urllib.parse import urlparse
from lok_sabha_rag.config import DATA_DIR

@lru_cache(maxsize=2)
def _read(path,mtime):
    data=json.loads(path.read_text(encoding='utf-8'))
    return data if isinstance(data,dict) else {}

def mapping():
    path=DATA_DIR/'rajya_sabha'/'pdf-links.json'
    try:return _read(path,path.stat().st_mtime_ns)
    except (OSError,ValueError):return {}

def verified_document(payload):
    if payload.get('house')!='rajya_sabha':return None
    data=mapping();source=payload.get('source') or {}
    item=data.get('links',{}).get(payload.get('question_id'),{})
    dataset=source.get('dataset','anudit/rajyasabha-qa')
    if item.get('dataset',data.get('dataset'))!=dataset or item.get('dataset_revision',data.get('dataset_revision'))!=source.get('dataset_revision'):
        return None
    if item.get('verified') is not True:return None
    for field in ('session_no','ques_no','date'):
        if str(item.get(field))!=str(payload.get(field)):return None
    if str(item.get('type','')).strip().upper()!=str(payload.get('type','')).strip().upper():return None
    if item.get('title')!=payload.get('subject'):return None
    url=item.get('url','');parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname!='sansad.in' or parsed.username or parsed.password:return None
    try:
        if parsed.port not in (None,443):return None
    except ValueError:return None
    if not parsed.path.startswith(f"/getFile/annex/{payload.get('session_no')}/") or not parsed.path.lower().endswith(('.pdf','.docx')):return None
    return url

def verified_pdf(payload):
    url=verified_document(payload)
    return url if url and urlparse(url).path.lower().endswith('.pdf') else None
