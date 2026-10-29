"""Source-dated public minister directory. Portfolios are never LLM-generated."""
import json
import re
from functools import lru_cache
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[1] / 'resources' / 'ministers.json'


@lru_cache(maxsize=2)
def _load(filename, mtime):
    return json.loads(Path(filename).read_text(encoding='utf-8'))


def catalogue():
    try:
        return _load(str(SNAPSHOT), SNAPSHOT.stat().st_mtime_ns)
    except (OSError, ValueError):
        return {'generated_at':None, 'jurisdictions':[], 'records':[]}


def search(query='', level='all', jurisdiction='', portfolio='', rank='', page=1, page_size=18):
    data=catalogue()
    scopes=[s for s in data['jurisdictions'] if (level=='all' or s['level']==level) and (not jurisdiction or s['id']==jurisdiction)]
    allowed={s['id'] for s in scopes}
    candidates=[r for r in data['records'] if r['jurisdiction_id'] in allowed]
    portfolios=sorted({p for r in candidates for p in r['portfolios'] if len(p)<=300},key=str.casefold)
    words=re.findall(r'\w+',query.casefold())
    chief_minister='cm' in words
    tokens=[t for t in words if t not in {'ministry','department','minister','of','for','the','and','who','is','cm'}]
    rows=[]
    for r in candidates:
        if chief_minister and ('chief minister' not in r['rank'].casefold() or 'deputy' in r['rank'].casefold()):continue
        hay=' '.join([r['name'],r['jurisdiction'],r['rank'],r['portfolio_text'],*r.get('aliases',[])]).casefold()
        if any(t not in hay for t in tokens):continue
        if portfolio and portfolio not in r['portfolios']:continue
        if rank and rank!=r['rank']:continue
        rows.append(r)
    rows.sort(key=lambda r:(r['jurisdiction_id']!='union',r['jurisdiction'],r['order']))
    start=(page-1)*page_size
    return {'records':rows[start:start+page_size],'total':len(rows),'page':page,'page_size':page_size,
        'portfolios':portfolios,'ranks':sorted({r['rank'] for r in candidates}),
        'jurisdictions':scopes,'snapshot_at':data['generated_at'],
        'coverage':{'minister_records':len(data['records']),'jurisdictions_with_records':sum(s.get('record_count',0)>0 for s in data['jurisdictions']),
            'jurisdictions_total':len(data['jurisdictions'])}}


def record(member_id):
    return next((r for r in catalogue()['records'] if r['id']==member_id),None)
