from fastapi import APIRouter,HTTPException
from lok_sabha_rag.core import record_people,bill_store,debate_store
from lok_sabha_rag.api.routes import profiles

router=APIRouter()


def decorate(data,lok_no=None):
    by_id,aliases=profiles.directory() if data['house']=='lok_sabha' else ({},{})
    for entry in data['people']:
        if data['house']=='rajya_sabha':
            from . import rs_profiles
            person=rs_profiles.person(entry['name'])
        else:
            person=profiles.person(entry['name'],by_id,aliases,lok_no)
            if not person['matched'] and data.get('kind')=='bill':
                from . import rs_profiles
                alternative=rs_profiles.person(entry['name'])
                if alternative['matched']:person=alternative
        if not person['matched']:person['profile_note']='Name and role are source-linked below. A verified biography/portrait match is not available in the current profile directory.'
        person.update(role_in_record='; '.join(entry['roles']),attribution_source_url=entry['source_url'],attribution_excerpt=entry.get('excerpt'))
        entry['profile']=person
    data['profile_note']='Portraits and biographies are shown only for unambiguous official profile matches. Party, constituency and career details reflect the profile when fetched, not necessarily the record date.'
    return data


@router.get('/debates/{record_id}/people')
def debate_people(record_id:str):
    row=debate_store.get_record(record_id)
    if not row or row.get('content_type')!='debate':raise HTTPException(404,'Debate not found')
    return decorate(record_people.debate_people(row),row.get('lok_no'))


@router.get('/bills/{bill_id}/people')
def bill_people(bill_id:str):
    row=bill_store.details(bill_id)
    if not row:raise HTTPException(404,'Bill not found')
    # The core cache must never be mutated by profile decoration.
    return decorate(record_people.bill_people(row))
