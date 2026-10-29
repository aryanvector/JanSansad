from fastapi import APIRouter, HTTPException, Query
from lok_sabha_rag.core import minister_store

router=APIRouter()


@router.get('/minister-directory')
def directory(query:str=Query('',max_length=200),level:str=Query('all',pattern='^(all|union|state|ut)$'),
              jurisdiction:str=Query('',max_length=80),portfolio:str=Query('',max_length=500),
              rank:str=Query('',max_length=100),page:int=Query(1,ge=1),page_size:int=Query(18,ge=1,le=60)):
    return minister_store.search(query,level,jurisdiction,portfolio,rank,page,page_size)


@router.get('/minister-directory/{member_id}/profile')
def profile(member_id:str):
    row=minister_store.record(member_id)
    if not row:raise HTTPException(404,'Minister record not found')
    if row['level']!='union':
        return {'name':row['name'],'matched':False,'profile_note':'Use this minister’s official state/UT source. A parliamentary profile is not assumed for a state minister.'}
    from . import profiles,rs_profiles
    members,aliases=profiles.directory()
    ls=profiles.person(row['name'],members,aliases,'18')
    rs=rs_profiles.person(row['name'])
    matches=[p for p in (dict(ls,profile_house='lok_sabha'),rs) if p['matched']]
    if len(matches)==1:return matches[0]
    return {'name':row['name'],'matched':False,'profile_note':'No single parliamentary identity could be verified. Refer to the official portfolio source.'}
