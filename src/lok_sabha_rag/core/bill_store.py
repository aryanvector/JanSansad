"""Read-only bill snapshot. House passage and origin are separate filters."""
import json
import re
from functools import lru_cache
from lok_sabha_rag.config import DATA_DIR


def path():return DATA_DIR/'bills'/'catalogue.json'


@lru_cache(maxsize=2)
def _load(filename,mtime):
    with open(filename,encoding='utf-8') as source:return json.load(source)


def catalogue():
    p=path()
    try:return _load(str(p),p.stat().st_mtime_ns)
    except (OSError,ValueError):return {'manifest':{'status':'not_imported','records':0},'records':[]}


def is_act(row):return bool(row.get('assent_date') or row.get('act_number'))


def matches(row,query='',tab='all',house='both',origin='both',year=None,ministry=None):
    # Search every meaningful catalogue field, not bill speech bodies.
    hay=' '.join(str(row.get(k) or '') for k in ('title','number','year','ministry','introduced_by','category','act_number','status')).casefold()
    if any(t not in hay for t in re.findall(r'\w+',query.casefold())):return False
    if origin!='both' and row.get('origin_house')!={'lok_sabha':'Lok Sabha','rajya_sabha':'Rajya Sabha'}[origin]:return False
    if year and row.get('year')!=year:return False
    if ministry and row.get('ministry')!=ministry:return False
    ls=bool(row.get('ls_passed_date'));rs=bool(row.get('rs_passed_date'))
    passed=ls if house=='lok_sabha' else rs if house=='rajya_sabha' else ls and rs
    if tab=='introduced':return bool(row.get('introduced_date'))
    if tab=='pending':return 'pending' in row.get('status','').casefold()
    if tab=='passed':return passed
    if tab=='acts':return is_act(row)
    return True


def list_bills(query='',tab='all',house='both',origin='both',year=None,ministry=None,page=1,page_size=12):
    data=catalogue(); common=dict(query=query,house=house,origin=origin,year=year,ministry=ministry)
    rows=[r for r in data['records'] if matches(r,tab=tab,**common)]
    counts={t:sum(matches(r,tab=t,**common) for r in data['records']) for t in ('all','introduced','pending','passed','acts')}
    start=(page-1)*page_size
    return {'records':rows[start:start+page_size],'total':len(rows),'page':page,'page_size':page_size,'counts':counts}


def details(bill_id):return next((r for r in catalogue()['records'] if r['id']==bill_id),None)
