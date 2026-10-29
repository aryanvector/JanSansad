"""Expose actual indexed RS coverage, not upstream dataset-wide claims."""
import json
from typing import Literal
from fastapi import APIRouter
from lok_sabha_rag.config import DATA_DIR
from .members import _load_all_members
from .ministries import _load_all_ministries
from lok_sabha_rag.core.pdf_links import mapping
from lok_sabha_rag.core import kaggle_store
from lok_sabha_rag.core import debate_store
from lok_sabha_rag.core import debate_fulltext
from lok_sabha_rag.core import coverage_inventory

router = APIRouter()

def rs_manifest():
    try:
        return json.loads((DATA_DIR/'rajya_sabha'/'manifest.json').read_text())
    except (OSError, ValueError):
        return {'status':'not_imported','records':0,'note':'Rajya Sabha pilot is not ready.'}

@router.get('/corpus-coverage')
def coverage():
    data = rs_manifest()
    kg=kaggle_store.manifest()
    data['sources']=[{'dataset':data.get('dataset'),'records':data.get('records',0),'date_from':data.get('date_from'),'date_to':data.get('date_to'),'retrieval':'semantic','licence':data.get('listed_license')}]
    if kg.get('status')=='ready':
        data['sources'].append({'dataset':kg['dataset'],'records':kg['records'],'date_from':kg['date_from'],'date_to':kg['date_to'],'retrieval':'keyword','licence':kg['listed_license']})
        data['hf_records']=data['records'];data['records']+=kg['records']
        data['dataset']='Hugging Face + Kaggle (deduplicated)'
        data['duplicate_rows_removed']=kg.get('audit',{}).get('duplicate_rows',0)+kg.get('audit',{}).get('overlap_with_active_hf',0)
        first = [v for v in [data.get('date_from'),kg.get('date_from')] if v]
        last = [v for v in [data.get('date_to'),kg.get('date_to')] if v]
        data['date_from']=min(first) if first else None
        data['date_to']=max(last) if last else None
        data['status']='ready'
        data['listed_license']='HF: MIT; Kaggle: CC-BY-SA-4.0'
    pdfs=mapping()
    entries=list(pdfs.get('links',{}).values())
    data['pdf_verified_records']=sum(entry.get('url','').split('?')[0].lower().endswith('.pdf') for entry in entries)
    data['other_verified_documents']=sum(entry.get('url','').split('?')[0].lower().endswith('.docx') for entry in entries)
    data['pdf_verified_at']=pdfs.get('generated_at') if data['pdf_verified_records'] else None
    archive=debate_store.manifest()
    data['debates']={k:v for k,v in archive.items() if k not in ('members','ministries')}
    data['lok_sabha_debates']={k:v for k,v in debate_store.manifest('lok_sabha').items() if k not in ('members','ministries')}
    data['debate_fulltext']=debate_fulltext.coverage()
    inventory = coverage_inventory.snapshot()
    data['inventory'] = inventory
    # Legacy callers: total catalogue identities across both Houses and Q&A.
    # Never present the old RS-only partial sum as an all-project total.
    qa = inventory.get('qa', {})
    data['all_records'] = (sum(s.get('records',0) for s in qa.values())
        + sum(s.get('records',0) for s in inventory.get('debate_catalogues',{}).values())) if inventory.get('status') == 'ready' else None
    data['all_records_basis'] = 'Q&A identities plus debate catalogue entries; excludes bills/ministers; not all full text'
    return {k:v for k,v in data.items() if k not in ('members','ministries')}

@router.get('/corpus-options')
def options(house: Literal['lok_sabha','rajya_sabha','both']='lok_sabha',content_type:Literal['qa','debate','all']='qa'):
    rs=rs_manifest()
    kg=kaggle_store.manifest()
    members = _load_all_members() if house != 'rajya_sabha' else []
    ministries = _load_all_ministries() if house != 'rajya_sabha' else []
    if house != 'lok_sabha':
        members = members + rs.get('members',[])
        ministries = ministries + rs.get('ministries',[])
        members += kg.get('members',[])
        ministries += kg.get('ministries',[])
    if content_type=='debate':members=[];ministries=[]
    if content_type!='qa' and house!='lok_sabha':
        archive=debate_store.manifest();members+=archive.get('members',[]);ministries+=archive.get('ministries',[])
    if content_type!='qa' and house!='rajya_sabha':
        archive=debate_store.manifest('lok_sabha');members+=archive.get('members',[]);ministries+=archive.get('ministries',[])
    return {'members':sorted(set(members)), 'ministries':sorted(set(ministries))}
