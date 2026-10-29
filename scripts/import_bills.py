"""Import a reproducible official bill catalogue snapshot (no credentials needed)."""
import argparse
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

API = 'https://sansad.in/api_rs/legislation/getBills'
SOURCES = ['https://sansad.in/ls/legislation/bills', 'https://sansad.in/rs/legislation/bills']
FILES = {'billIntroducedFile':'As introduced', 'billPassedInLSFile':'As passed by Lok Sabha',
         'billPassedInRSFile':'As passed by Rajya Sabha', 'billPassedInBothHousesFile':'As passed by both Houses',
         'billGazettedFile':'Gazette notification', 'reportFile':'Committee report',
         'errataFile':'Errata', 'billSynopsisFile':'Synopsis'}


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def date(value):
    value = clean(value)
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(value[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


def safe_url(value):
    try:
        p = urlparse(value)
        return (p.scheme == 'https' and p.hostname in ('sansad.in', 'www.sansad.in')
                and p.port in (None, 443) and not p.username and not p.password
                and p.path.startswith(('/getFile/', '/uploads/')))
    except ValueError:
        return False


def normalize(raw):
    title = clean(raw.get('billName'))
    if not title:
        return None
    introduced = date(raw.get('billIntroducedDate'))
    house = clean(raw.get('billIntroducedInHouse'))
    identity = [title.casefold(), clean(raw.get('billNumber')).casefold(), raw.get('billYear'),
                house.casefold(), introduced, clean(raw.get('billIntroducedBy')).casefold()]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
    docs = [{'label': label, 'url': raw[field]} for field, label in FILES.items()
            if raw.get(field) and safe_url(raw[field])]
    return dict(id='B_'+key, title=title, number=clean(raw.get('billNumber')),
                year=raw.get('billYear'), origin_house=house or None,
                type=clean(raw.get('billType')) or None, category=clean(raw.get('billCategory')) or None,
                ministry=clean(raw.get('ministryName')) or None, introduced_by=clean(raw.get('billIntroducedBy')) or None,
                introduced_date=introduced, ls_passed_date=date(raw.get('billPassedInLSDate')),
                rs_passed_date=date(raw.get('billPassedInRSDate')), status=clean(raw.get('status')) or 'Not supplied',
                source_statuses=[clean(raw.get('status')) or 'Not supplied'],
                assent_date=date(raw.get('billAssentedDate')), act_number=clean(raw.get('actNo')) or None,
                act_year=raw.get('actYear'), committee_date=date(raw.get('referredToCommitteeDate')),
                report_date=date(raw.get('reportPresentedDate')), documents=docs, sources=SOURCES,
                source_dates={field:raw.get(field) for field in ('billIntroducedDate','billPassedInLSDate','billPassedInRSDate','billAssentedDate')})


def merge_status_variants(existing, incoming):
    """Merge only otherwise identical rows; preserve every source status label."""
    without_status=lambda r:{k:v for k,v in r.items() if k not in ('status','source_statuses')}
    if without_status(existing)!=without_status(incoming):return False
    statuses=sorted(set(existing['source_statuses']+incoming['source_statuses']))
    existing['source_statuses']=statuses
    existing['status']=' / '.join(statuses)
    return True


def run(output, start=2009, end=2026):
    root = Path(output); root.mkdir(parents=True, exist_ok=True)
    cache = root/'source-pages'; cache.mkdir(exist_ok=True)
    rows=[]; page=1; total=None
    while True:
        dest=cache/f'page-{page}.json'
        if dest.exists(): data=json.loads(dest.read_text(encoding='utf-8'))
        else:
            url=API+'?'+urlencode(dict(page=page,size=1000,locale='en',sortOn='billIntroducedDate',sortBy='desc'))
            for attempt in range(3):
                try:
                    data=json.load(urlopen(Request(url,headers={'User-Agent':'SansadAI/1.0'}),timeout=60)); break
                except Exception:
                    if attempt==2:raise
                    time.sleep(1+attempt)
            dest.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        meta=data['_metadata']
        if total is None:total=meta['totalElements']
        if meta['totalElements']!=total:raise RuntimeError('Catalogue changed during import; retry with fresh source cache')
        rows.extend(data['records'])
        print(f'Fetched page {page}/{meta["totalPages"]}',flush=True)
        if page>=meta['totalPages']:break
        page+=1
    if len(rows)!=total:raise RuntimeError('Incomplete catalogue response')
    records={}; audit=Counter(); conflict=[]
    for raw in rows:
        r=normalize(raw)
        if not r:audit['missing_title']+=1;continue
        if not isinstance(r['year'],int) or not start<=r['year']<=end:audit['outside_year_range']+=1;continue
        if r['id'] in records:
            if r==records[r['id']]:audit['exact_duplicates']+=1
            elif merge_status_variants(records[r['id']],r):audit['status_variants_merged']+=1
            else:
                # Preserve source variants; never merge conflicting statuses or bill versions.
                audit['conflicting_identity_variants']+=1
                suffix=hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest()[:10]
                r['id']+='_'+suffix
                if r['id'] in records:audit['exact_duplicates']+=1;continue
                conflict.append(r['id']);records[r['id']]=r
        else:records[r['id']]=r
    items=sorted(records.values(),key=lambda r:(r['introduced_date'] or '',r['title'],r['id']),reverse=True)
    dates=[r['introduced_date'] for r in items if r['introduced_date']]
    manifest=dict(status='ready',source='Digital Sansad Bills catalogue',source_urls=SOURCES,endpoint=API,
        requested_year_from=start,requested_year_to=end,reported_rows=total,records=len(items),
        date_from=min(dates),date_to=max(dates),years=dict(sorted(Counter(r['year'] for r in items).items())),
        origin_houses=dict(Counter(r['origin_house'] for r in items)),official_statuses=dict(Counter(r['status'] for r in items)),
        audit=dict(audit),conflicting_ids=conflict,imported_at=datetime.now(timezone.utc).isoformat(),
        note='Official metadata snapshot; document links are source-provided, not all individually verified. Missing fields do not prove an event did not occur.')
    document={'manifest':manifest,'records':items}
    pending=root/'catalogue.pending';pending.write_text(json.dumps(document,ensure_ascii=False),encoding='utf-8');pending.replace(root/'catalogue.json')
    print(json.dumps({k:v for k,v in manifest.items() if k!='conflicting_ids'},indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output');parser.add_argument('--from-year',type=int,default=2009);parser.add_argument('--to-year',type=int,default=2026)
    a=parser.parse_args();run(a.output,a.from_year,a.to_year)
