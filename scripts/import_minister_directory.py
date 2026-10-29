"""Build a source-dated directory from reviewed official HTML snapshots.

Run with BeautifulSoup installed, passing the source snapshot directory.
No LLM extraction; uncertain layouts stay unimported, never guessed.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]


def clean(value):
    return re.sub(r'\s+',' ',str(value or '')).strip()


def split_portfolios(value):
    value=clean(value)
    parts=re.split(r';|(?<!\d)\b\d{1,2}[.)]\s*|\s*\|\s*',value)
    out=[]
    for p in parts:
        p=re.sub(r'^\s*(?:and\s+)?(?:Prime Minister and also in-charge of:\s*)?(?:Minister of State\s*\(Independent Charge\)\s*(?:of|in)\s*(?:the\s*)?|Minister of State\s*(?:of|in)\s*(?:the\s*)?|Minister of\s*)','',p,flags=re.I)
        p=re.sub(r'^(?:the\s+)?Ministry of\s+','',p,flags=re.I).strip(' .,:-')
        if p and p.lower()!='and' and p not in out:out.append(p)
    return out


def build(directory):
    sources=json.loads((ROOT/'scripts/minister_sources.json').read_text())
    records=[];scopes=[]
    aliases={'telangana':'telangana-final','karnataka':'karnataka-final','jammu-and-kashmir':'jammu-and-kashmir-alt','tamil-nadu':'tamil-nadu-found','madhya-pradesh':'madhya-pradesh-found'}
    for source in sources:
        key=source['id'];file=directory/(aliases.get(key,key)+'.html')
        scope={'id':key,'name':source['name'],'level':source['level'],'source_url':source['url'],'as_of':None,'fetched_at':None,'status':'not_imported','status_label':'Roster not yet verified','note':'Official roster import is incomplete. Do not interpret missing records as vacant offices.','record_count':0}
        if source.get('administration_only'):
            scope.update(status='administration',status_label='Administration portal',note='This UT is administered without a state-style elected Council of Ministers. Administrators, Lieutenant Governors and local hill-council executives are not listed as state ministers.')
            scopes.append(scope);continue
        if not file.exists():scopes.append(scope);continue
        soup=BeautifulSoup(file.read_text(encoding='utf-8'),'html.parser')
        dumpfile=file.with_suffix('.json')
        dump=json.loads(dumpfile.read_text(encoding='utf-8')) if dumpfile.exists() else {}
        scope['source_url']=dump.get('url',source['url'])
        scope['fetched_at']=datetime.fromtimestamp(file.stat().st_mtime,timezone.utc).isoformat()
        scope['source_sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
        tables=[]
        for table in soup.select('table'):
            # Nested layout tables must not make every descendant a single person.
            if table.find('table'):continue
            tables.append([[c for c in tr.find_all(['th','td'],recursive=False)] for tr in table.select('tr')])
        def add(name,rank,portfolio='',url=None,as_of=None,portfolios=None):
            name=clean(name);rank=clean(rank) or 'Minister (source list)'
            if len(name)<3 or len(name)>180 or re.search(r'@|\b(?:Address|Phone|Mobile|Fax)\b',name,re.I):return
            identity=re.sub(r'[^\w]','',name.casefold())
            existing=next((r for r in records if r['jurisdiction_id']==key and r['identity']==identity),None)
            parts=portfolios if portfolios is not None else split_portfolios(portfolio)
            if existing:
                existing['portfolios']=list(dict.fromkeys(existing['portfolios']+parts));existing['portfolio_text']='; '.join(existing['portfolios']);return
            records.append({'id':'M_'+hashlib.sha256((key+':'+identity).encode()).hexdigest()[:20],'identity':identity,'name':name,'rank':rank,
                'level':source['level'],'jurisdiction_id':key,'jurisdiction':source['name'],'portfolios':parts,'portfolio_text':clean(portfolio) or '; '.join(parts),
                'source_url':url or scope['source_url'],'as_of':as_of or scope['as_of'],'fetched_at':scope['fetched_at'],'order':sum(r['jurisdiction_id']==key for r in records)})
        def cells(row):return [clean(c.get_text(' ',strip=True)) for c in row]
        def name_role(value,default='Minister (source list)'):
            value=clean(value)
            match=re.search(r"(?:Hon[’']?ble\s+)?(?:Honourable\s+)?(Deputy Chief Minister|Chief Minister|Cabinet Minister|Minister of State(?:\s*\(Independent Charge\))?|Minister)\b",value,re.I)
            if match:return value[:match.start()].strip(),match[1]
            return value,default
        if key=='union':
            scope['as_of']='2026-07-25'
            rank='Prime Minister';union_start=len(records)
            for table in tables:
                for row in table:
                    c=cells(row)
                    if len(c)==1 and c[0] in ('Cabinet Ministers','Ministers of State (Independent Charge)','Ministers of State'):rank=c[0].replace('Ministers','Minister');continue
                    if len(c)==2 and c[0].startswith('Shri Narendra'):add(c[0],'Prime Minister',c[1])
                    elif len(c)==3 and c[0].isdigit():add(c[1],rank,c[2])
            # Compare every numbered minister against the newer Cabinet Secretariat
            # roster. The older HTML remains the legible portfolio transcription.
            latest=directory/'union-latest-layout.txt'
            if latest.exists():
                text=latest.read_text(encoding='utf-8').split('Note:')[0]
                blocks=re.split(r'(?m)^\s*\d+\s*\.?\s+(?=Shri|Smt|Dr\.|Prof\.|Rao|Sushri)',text)[1:]
                def words(s):return re.findall(r'[a-z]+',s.casefold().replace('kirtivardhan','kirti vardhan'))
                def in_order(needle,hay):
                    it=iter(hay);return all(any(v==n for v in it) for n in needle)
                selected=[]
                for row in records[union_start:]:
                    if row['rank']=='Prime Minister':selected.append(row);continue
                    nw=words(row['name']);matches=[b for b in blocks if in_order(nw,words(' '.join(b.splitlines()[:3])))]
                    if len(matches)==1:selected.append(row)
                if len(blocks)!=67 or len(selected)!=68:raise ValueError('New Union roster identity check failed; review before importing')
                records[union_start:]=selected
                scope['as_of']='2026-10-15';scope['source_url']='https://cabsec.gov.in/writereaddata/councilofministers/english/1_Upload_4295.pdf'
                for row in selected:
                    row.update(as_of=scope['as_of'],source_url=scope['source_url'],transcription_source=source['url'],transcription_as_of='2026-07-25')
                scope['note']='Names were checked against the 15 October Cabinet Secretariat PDF. Portfolio transcription uses the readable 25 July PMO table and has not been independently validated for every subsequent portfolio change; consult the latest PDF.'
        elif key in ('bihar','arunachal-pradesh','haryana','himachal-pradesh','meghalaya','mizoram','nagaland','sikkim','telangana','uttarakhand','delhi','tamil-nadu'):
            mapping={'bihar':(2,3,4),'arunachal-pradesh':(1,2,None),'haryana':(2,None,4),'himachal-pradesh':(0,1,2),'meghalaya':(0,None,1),'mizoram':(1,2,3),'nagaland':(1,None,2),'sikkim':(0,1,3),'telangana':(1,None,2),'uttarakhand':(2,None,4),'delhi':(1,None,2),'tamil-nadu':(1,None,2)}
            ni,ri,pi=mapping[key]
            for table in tables:
                header=' '.join(cells(table[0])).lower() if table else ''
                if not any(x in header for x in ('name','minister')):continue
                if key=='himachal-pradesh' and 'portfolio' not in header:continue
                if key=='nagaland' and 'portfolio' not in header:continue
                if key=='mizoram' and 'departments' not in header:continue
                for row in table[1:]:
                    c=cells(row)
                    if len(c)<=max(ni,ri or 0,pi or 0):continue
                    if key!='himachal-pradesh' and not c[0].strip('. ').isdigit() and key not in ('meghalaya','sikkim','telangana'):continue
                    name,rank=name_role(c[ni],c[ri] if ri is not None else 'Minister (source list)')
                    raw=c[pi] if pi is not None else ''
                    if not name and key=='telangana':name=c[ni]
                    if key=='nagaland':
                        for title in ('Deputy Chief Minister','Chief Minister'):
                            if title.lower() in raw.lower():rank=title;break
                    if key=='telangana':
                        if 'Dy.Chief Minister' in raw:rank='Deputy Chief Minister'
                        elif 'Chief Minister' in raw:rank='Chief Minister'
                    add(name,rank,raw)
            # The linked Chief Minister pages are separate from these cabinet lists.
            if key=='uttarakhand':
                cm=directory/'uttarakhand-cm.html'
                if cm.exists():
                    cs=BeautifulSoup(cm.read_text(encoding='utf-8'),'html.parser')
                    for table in cs.select('table'):
                        rows=table.select('tr')
                        if 'Portfolio' not in table.get_text():continue
                        for row in rows[1:]:
                            c=[x.get_text(' ',strip=True) for x in row.find_all(['td','th'],recursive=False)]
                            if len(c)==3 and c[0].strip().isdigit():add(c[1],'Chief Minister',c[2],url='https://cm.uk.gov.in/about-chief-minister/')
            if key=='delhi':
                cm=directory/'delhi-cm.html'
                if cm.exists():
                    cs=BeautifulSoup(cm.read_text(encoding='utf-8'),'html.parser');text=cs.get_text(' ',strip=True)
                    match=re.search(r'Portfolio\s+(.*?)\s+Cabinet Ministers CMO Officials',text)
                    if match and 'Smt. Rekha Gupta' in text:add('Smt. Rekha Gupta','Chief Minister',match[1],url='https://delhi.gov.in/cmo')
        elif key=='kerala':
            for table in tables:
                for row in table:
                    c=cells(row)
                    if len(c)==2 and re.match(r'(Shri|Smt)\b',c[0]):add(c[0],'Chief Minister' if c[1].startswith('Chief Minister') else 'Minister (source list)',c[1])
        elif key=='madhya-pradesh':
            api=directory/'madhya-pradesh-data.json'
            if api.exists():
                for row in json.loads(api.read_text(encoding='utf-8')):
                    add(row.get('Minister_Name'),row.get('DesignationName'),row.get('Department'))
                scope['note']='Names and designations from the official MP Information Department API. Portfolios absent from that response are left blank.'
        elif key=='west-bengal':
            for table in tables:
                for row in table:
                    c=cells(row)
                    if len(c)<5 or not c[0].isdigit():continue
                    for col,rank in ((2,'Minister-in-Charge'),(3,'Minister of State (Independent Charge)'),(4,'Minister of State')):
                        if c[col] and c[col] not in ('-','--','N/A'):add(c[col],rank,c[1],portfolios=[c[1]])
        elif key=='karnataka':
            for table in tables:
                for row in table:
                    c=cells(row)
                    if len(c)>=3 and c[0].strip('. ').isdigit():
                        name,rank=name_role(c[1]);add(name,rank,c[-1])
        elif key=='manipur':
            for card in soup.select('a.box-member[href*="/members/profile/"]'):
                divs=card.find_all('div',recursive=False)
                if len(divs)>=4:add(divs[1].get_text(' ',strip=True),divs[2].get_text(' ',strip=True),divs[3].get_text(' | ',strip=True),url=urljoin(scope['source_url'],card['href']))
        elif key=='jammu-and-kashmir':
            for table in soup.select('table'):
                text=table.get_text(' ',strip=True)
                if text.count('View Profile')!=1:continue
                match=re.search(r"View Profile\s+(.*?)\s+DOB\s*:.*?(Hon[’']ble.*?)\s+Off Address",text)
                if match:
                    name=match[1];role=match[2];rank='Deputy Chief Minister' if 'Deputy Chief Minister' in role else 'Chief Minister' if 'Chief Minister' in role else 'Minister (source list)'
                    portfolio=re.sub(r"^Hon[’']ble\s+(?:Deputy Chief Minister|Chief Minister|Minister)(?:\s+for)?\s*",'',role).strip(' ().')
                    add(name,rank,portfolio)
        elif key=='puducherry':
            for card in soup.select('.table-bordered'):
                h=card.select_one('h3');text=card.get_text(' ',strip=True)
                if not h or 'Portfolio' not in text:continue
                name=h.get_text(' ',strip=True);role=text.split(name)[0];portfolio=text.split('Portfolio',1)[1]
                # Contact fields are explicitly excluded; only the portfolio tail is used.
                name,rank=name_role(name,'Chief Minister' if 'Chief Minister' in role else 'Minister (source list)');add(name,rank,portfolio)
        elif key=='maharashtra':
            for card in soup.select('.member'):
                h=card.select_one('h4');ps=card.select('p')
                if h:add(h.get_text(),'Minister (source list)','')
            scope['note']='This eCabinet page lists names in Marathi, without portfolios. Minister-of-State coverage and English-name search are incomplete.'
        elif key=='goa':
            for card in soup.select('.profile_column_holder'):
                n=card.select_one('.column_name');role=card.select_one('.column_designation');link=card.select_one('a[href*="/ministers/"]')
                if n and link:add(n.get_text(),'Chief Minister' if role and 'Chief Minister' in role.get_text() else 'Minister (source list)','',url=link['href'])
            scope['as_of']='2025-08-27';scope['note']='Roster notification date supplied by the official source. Detailed portfolios require the individual official profile pages.'
        elif key=='odisha':
            for card in soup.select('.card-footer'):
                heads=card.select('h3,h4')
                if heads:
                    name=heads[0].get_text();role=heads[1].get_text() if len(heads)>1 else 'Minister (source list)';add(name,role,'')
            scope['note']='Official Assembly roster imported; portfolio detail is not supplied on this listing page.'
        elif key=='tripura':
            for table in tables:
                for row in table:
                    c=cells(row)
                    if len(c)<2 or not re.search(r'(Shri|Smt|Prof\.)',c[0]):continue
                    value=c[0];rank='Chief Minister' if 'Chief Minister' in value else 'Minister (source list)'
                    value=re.sub(r"^Hon[’']?ble\s+(?:Chief Minister|Minister)\s*",'',value)
                    add(value,rank,c[1])
        scope['record_count']=sum(r['jurisdiction_id']==key for r in records)
        if scope['record_count']:
            missing=sum(not r['portfolios'] for r in records if r['jurisdiction_id']==key)
            scope.update(status='partial' if missing else 'snapshot',status_label='Partial roster / portfolios' if missing else 'Official-source snapshot')
            if not scope['note'].startswith(('Names were','This eCabinet','Roster notification','Official Assembly')):
                scope['note']='Source list imported; its completeness and current appointment status are not independently guaranteed. See each record’s official source.'
        for row in records:
            if row['jurisdiction_id']==key:
                if not row['as_of']:row['as_of']=scope['as_of']
                row.pop('identity',None)
        scopes.append(scope)
    supplement_file=ROOT/'scripts/minister_verified_supplements.json'
    if supplement_file.exists():
        for entry in json.loads(supplement_file.read_text(encoding='utf-8')):
            scope=next(s for s in scopes if s['id']==entry['jurisdiction_id'])
            identity=re.sub(r'[^\w]','',entry['name'].casefold())
            identifier='M_'+hashlib.sha256((scope['id']+':'+identity).encode()).hexdigest()[:20]
            if any(r['id']==identifier for r in records):continue
            records.append({k:v for k,v in entry.items() if k!='scope_note'} | {
                'id':identifier,'level':scope['level'],'jurisdiction':scope['name'],
                'portfolio_text':'; '.join(entry['portfolios']),
                'order':sum(r['jurisdiction_id']==scope['id'] for r in records)})
            scope.update(status='partial',status_label='Partial roster — verified individual record',
                record_count=sum(r['jurisdiction_id']==scope['id'] for r in records),
                source_url=entry['source_url'],fetched_at=entry['fetched_at'],source_sha256=entry['source_sha256'],
                note=entry['scope_note'])
    return {'generated_at':datetime.now(timezone.utc).isoformat(),'jurisdictions':scopes,'records':records}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('snapshot_directory',type=Path);parser.add_argument('--output',type=Path,default=ROOT/'src/lok_sabha_rag/resources/ministers.json');args=parser.parse_args()
    result=build(args.snapshot_directory);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'records':len(result['records']),'coverage':{s['name']:s['record_count'] for s in result['jurisdictions']}},ensure_ascii=True))
