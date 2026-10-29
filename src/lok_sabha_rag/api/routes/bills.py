from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from lok_sabha_rag.core import bill_store
from lok_sabha_rag.core import bill_documents as documents
from lok_sabha_rag.core import coverage_inventory

router=APIRouter()


@router.get('/bills/coverage')
def coverage():
    data=bill_store.catalogue()
    inventory = coverage_inventory.snapshot()
    return {**data['manifest'], 'records':len(data['records']),
        'document_coverage':inventory.get('bills'), 'coverage_checked_at':inventory.get('checked_at'),
        'ministries':sorted({r['ministry'] for r in data['records'] if r.get('ministry')})}


@router.get('/bills')
def search(query:str=Query('',max_length=300),tab:Literal['all','introduced','pending','passed','acts']='all',
           house:Literal['both','lok_sabha','rajya_sabha']='both',origin:Literal['both','lok_sabha','rajya_sabha']='both',
           year:int|None=Query(None,ge=1900,le=2100),ministry:str|None=None,
           page:int=Query(1,ge=1),page_size:int=Query(12,ge=1,le=50)):
    return bill_store.list_bills(query,tab,house,origin,year,ministry,page,page_size)


@router.get('/bills/{bill_id}')
def details(bill_id:str):
    row=bill_store.details(bill_id)
    if not row:raise HTTPException(404,'Bill not found in the imported catalogue')
    return row


BillVersion=Literal['introduced','ls_passed','rs_passed','both_passed','gazette']


class DocumentRequest(BaseModel):
    version:BillVersion='introduced'


class BillQuestion(DocumentRequest):
    question:str=Field(...,min_length=3,max_length=700)
    synthesize:bool=True


def record(bill_id):
    row=bill_store.details(bill_id)
    if not row:raise HTTPException(404,'Bill not found in the imported catalogue')
    return row


@router.get('/bills/{bill_id}/versions')
def versions(bill_id:str):
    return {'versions':documents.versions(record(bill_id))}


@router.post('/bills/{bill_id}/document')
def prepare(bill_id:str,req:DocumentRequest):
    try:
        data=documents.prepare(record(bill_id),req.version)
        return {k:v for k,v in data.items() if k!='pages'}
    except documents.DocumentError as error:raise HTTPException(error.status,str(error)) from None


@router.post('/bills/{bill_id}/ask')
def ask(bill_id:str,req:BillQuestion):
    if not req.question.strip():raise HTTPException(422,'Please enter a question.')
    try:return documents.answer(record(bill_id),req.version,req.question.strip(),req.synthesize)
    except documents.DocumentError as error:raise HTTPException(error.status,str(error)) from None


@router.get('/bills/{bill_id}/pdf')
def pdf(bill_id:str,version:BillVersion='introduced'):
    row=record(bill_id)
    try:
        data=documents.cached(row,version)
        if not data:raise HTTPException(404,'Load this document before opening the cached PDF.')
        return FileResponse(documents.folder(row,version)/'original.pdf',media_type='application/pdf',
                            filename=bill_id+'-'+version+'.pdf',content_disposition_type='inline')
    except documents.DocumentError as error:raise HTTPException(error.status,str(error)) from None


@router.get('/bills/{bill_id}/pages/{page}')
def page_text(bill_id:str,page:int,version:BillVersion='introduced'):
    try:
        data=documents.cached(record(bill_id),version)
        if not data or not 1<=page<=data['page_count']:raise HTTPException(404,'Page not found. Load the selected PDF first.')
        return {**data['pages'][page-1],'version_label':data['version_label'],'source_url':data['source_url']}
    except documents.DocumentError as error:raise HTTPException(error.status,str(error)) from None
