"""Official Rajya Sabha identities, portraits and biographies, including former MPs."""
import re
import time
import threading
from datetime import datetime,timezone
from urllib.parse import urlparse
from urllib.request import Request,urlopen,build_opener,HTTPRedirectHandler
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from lok_sabha_rag.api.routes import profiles

router=APIRouter();_index=None;_time=0;_lock=threading.Lock()


def safe_photo(value):
    value=str(value or '').strip()
    if value.startswith('/getFile/rsnew/'):value='https://sansad.in'+value
    try:
        p=urlparse(value)
        return value if p.scheme=='https' and p.hostname=='sansad.in' and p.port in (None,443) and not p.username and not p.password and p.path.startswith('/getFile/rsnew/member_site/photos/') else None
    except ValueError:return None


def directory():
    global _index,_time
    if _index is not None and time.time()-_time<86400:return _index
    with _lock:
        if _index is not None and time.time()-_time<86400:return _index
        entry=profiles.cached_json('rs-members-all','https://sansad.in/api_rs/member/member-list')
        sitting=profiles.cached_json('rs-members-sitting','https://rsdoc.nic.in/MemberGetData/getmemberall')
        current={int(x['MP_CODE']):x for x in (sitting or {}).get('data',[]) if x.get('MP_CODE')}
        members={};aliases={}
        for row in (entry or {}).get('data',[]):
            code=int(row['mpCode']);extra=current.get(code,{})
            members[code]={'name':profiles.clean(row.get('mpName') or row.get('name')),
                'party':profiles.clean(row.get('partyName')),'state':profiles.clean(extra.get('STATE_NAME')),
                'photo_url':safe_photo(extra.get('PHOTO_DSP')),'retrieved_at':datetime.fromtimestamp(entry['time'],timezone.utc).isoformat()}
            for name in (row.get('mpName'),row.get('name')):
                if name:aliases.setdefault(profiles.normalise(name),set()).add(code)
        _index=(members,aliases);_time=time.time() if members else time.time()-86340
        return _index


def biography(member_id):
    members,_=directory()
    if member_id not in members:raise HTTPException(404,'Rajya Sabha member not found in the official directory.')
    bio=profiles.cached_json(f'rs-bio-{member_id}',f'https://sansad.in/api_rs/member/bio-data?mpCode={member_id}&locale=en')
    if not bio or not isinstance(bio.get('data'),dict) or bio['data'].get('mpCode')!=member_id:
        raise HTTPException(503,'Official Rajya Sabha biography is unavailable. Use the source profile link.')
    b=bio['data'];positions=profiles.cached_json(f'rs-positions-{member_id}',f'https://sansad.in/api_rs/member/position-held?mpCode={member_id}&locale=en')
    career=[{'period':profiles.clean(x.get('period')),'position':profiles.clean(x.get('position'))} for x in (positions or {}).get('data',[]) if isinstance(x,dict)]
    return {'id':member_id,'profile_house':'rajya_sabha','name':profiles.clean(b.get('name')),
        'photo_url':safe_photo(b.get('imageUrl')),'party':profiles.clean(b.get('party')),'state':profiles.clean(b.get('state')),
        'education':profiles.clean(b.get('qualification')),'date_of_birth':profiles.clean(b.get('dateBirth')),
        'terms':profiles.clean(b.get('previousMembership')),'career':career,'career_available':positions is not None,
        'retrieved_at':datetime.fromtimestamp(bio['time'],timezone.utc).isoformat(),
        'career_retrieved_at':datetime.fromtimestamp(positions['time'],timezone.utc).isoformat() if positions else None,
        'profile_url':f'https://sansad.in/rs/members/biographyM/{member_id}'}


def person(name):
    members,aliases=directory();candidates=aliases.get(profiles.normalise(name),set())
    if len(candidates)!=1:return {'name':profiles.clean(name),'matched':False,'profile_house':'rajya_sabha','profile_note':'No unique official Rajya Sabha identity match was found. The source name is preserved.'}
    code=next(iter(candidates));item=members[code]
    # The all-member index has retired names but not all portrait/state fields.
    if not item.get('photo_url') or not item.get('state'):
        try:
            bio=biography(code);item={**item,**{k:bio[k] for k in ('photo_url','state','retrieved_at')}}
        except HTTPException:pass
    return {**item,'id':code,'matched':True,'profile_house':'rajya_sabha','profile_url':f'https://sansad.in/rs/members/biographyM/{code}'}


def question_context(chunks,text):
    first=chunks[0];asked=[person(n) for n in profiles.names(first.asked_by)]
    heading=profiles.answerer(text)
    answered=None
    if heading:
        answered=person(heading['name'])
        if not answered['matched']:
            members,aliases=profiles.directory();alternative=profiles.person(heading['name'],members,aliases)
            if alternative['matched']:answered={**alternative,'profile_house':'lok_sabha'}
        answered['role_in_record']=heading['role_in_record']
    return {'asked_by':asked,'answered_by':answered,'record_date':first.date,'ministry':first.ministry,'source_url':first.pdf_url,
        'profile_note':'Names are matched to official House-specific directories. Profile party/state/career reflect the source when fetched, not necessarily the historical answer date.',
        'answerer_note':None if answered else 'The answering minister is not identifiable from an explicit answer heading in the available text. No name was inferred.'}


@router.get('/rs-profiles/{member_id}')
def profile(member_id:int):return biography(member_id)


class PhotoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not safe_photo(newurl):raise ValueError('Unapproved portrait redirect')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


@router.get('/rs-profile-photo/{member_id}')
def photo(member_id:int):
    members,_=directory()
    if member_id not in members:raise HTTPException(404,'Member portrait not found.')
    url=members[member_id].get('photo_url')
    if not url:url=biography(member_id).get('photo_url')
    if not safe_photo(url):raise HTTPException(404,'Official portrait not available.')
    try:
        with build_opener(PhotoRedirect()).open(Request(url,headers={'User-Agent':'SansadAI/1.0'}),timeout=10) as response:
            kind=response.headers.get_content_type();data=response.read(3_000_001)
        if kind not in ('image/jpeg','image/png','image/webp') or len(data)>3_000_000:raise ValueError('Invalid portrait')
        return Response(data,media_type=kind,headers={'Cache-Control':'public, max-age=86400'})
    except Exception:raise HTTPException(503,'The official portrait is temporarily unavailable.') from None
