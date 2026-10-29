from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest

from lok_sabha_rag.core.comparison_slots import plan_slots, retrieve_slots
from lok_sabha_rag.core.scoped_retrieval import retrieve_scoped, scope_context
from lok_sabha_rag.core.retriever import _extract_evidence


QUERY = 'Compare Aurora hospital capacity in the Rajya Sabha reply of 8 July 2023 and Borealis school vacancies in the Lok Sabha reply of 9 June 2024.'


def item(qid, text, day, house):
    return replace(_extract_evidence(NS(id=qid,score=.8,payload={
        'question_id':qid,'text':text,'date':day,'subject':text,'lok_no':18,
        'session_no':1,'ques_no':1,'type':'UNSTARRED','source':{'chunk_index':0}}),score=.8),house=house)


def setup():
    a=item('a','Aurora hospital capacity 80 beds','2023-07-08','rajya_sabha')
    b=item('b','Borealis school vacancies 20 posts','2024-06-09','lok_sabha')
    wrong=item('x','Museum conservation grants 900','2024-06-09','lok_sabha')
    r=Mock()
    r.search.side_effect=lambda **kw: [a] if kw['record_dates']==['2023-07-08'] else [wrong,b]
    r._fetch_leading_chunks.side_effect=lambda **kw:{'a':[a],'b':[b],'x':[wrong]}[kw['question_id']]
    return r,a,b,wrong


def test_binds_different_topics_and_houses_without_global_conjunction():
    p=plan_slots(QUERY)
    assert p[0]['house']=='rajya_sabha' and p[1]['house']=='lok_sabha'
    assert 'Aurora' in p[0]['topic'] and 'Aurora' not in p[1]['topic']
    r,*_=setup()
    items,plan=retrieve_scoped(r,QUERY,9,2,1,house='both',content_type='qa',ministry='example',mp_names=['Member'])
    assert {i.question_id for i in items}=={'a','b'}
    assert all(s['status']=='matched' for s in plan['comparison_slots'])
    assert sum(c.kwargs['top_k'] for c in r.search.call_args_list)==9
    assert [c.kwargs['house'] for c in r.search.call_args_list]==['rajya_sabha','lok_sabha']
    assert all(c.kwargs['ministry']=='example' and c.kwargs['mp_names']==['Member'] for c in r.search.call_args_list)


def test_same_date_wrong_topic_is_missing_not_substitute():
    r,a,b,wrong=setup()
    r.search.side_effect=lambda **kw:[a] if kw['house']=='rajya_sabha' else [wrong]
    items,p=retrieve_slots(r,QUERY,8,4,2,house='both')
    assert {i.question_id for i in items}=={'a'}
    assert p['comparison_slots'][1]['status']=='missing_matching_evidence'
    assert 'NOT the requested reply' in scope_context(p)


@pytest.mark.parametrize('bad_date,bad_house',[('2020-01-01','lok_sabha'),('2024-06-09','rajya_sabha')])
def test_backend_wrong_date_or_house_is_rejected(bad_date,bad_house):
    r,a,b,_=setup()
    b=replace(b,date=bad_date,house=bad_house)
    r.search.side_effect=lambda **kw:[a] if kw['house']=='rajya_sabha' else [b]
    items,p=retrieve_slots(r,QUERY,8,4,2,house='both')
    assert {i.question_id for i in items}=={'a'}


def test_conflicting_house_filter_not_relaxed():
    r,*_=setup()
    _,p=retrieve_slots(r,QUERY,8,4,2,house='lok_sabha')
    assert r.search.call_count==1
    assert p['comparison_slots'][0]['status']=='missing_matching_evidence'


def test_shared_topic_inherits_and_small_budget_reports_omission():
    q='Compare Meridian bridge capacity in replies of 8 July 2023 and 9 June 2024'
    p=plan_slots(q)
    assert p[0]['topic']==p[1]['topic']
    r=Mock(); a=item('a','Meridian bridge capacity 10','2023-07-08','lok_sabha'); b=replace(a,question_id='b',date='2024-06-09')
    r.search.side_effect=[[a],[b]]
    r._fetch_leading_chunks.side_effect=[[a],[b]]
    items,p=retrieve_slots(r,q,2,1,1,house='both')
    assert len(items)==1 and len(p['missing_dates'])==1


def test_single_shared_house_applies_to_both_dates():
    slots=plan_slots('Compare Meridian bridge capacity in Lok Sabha replies of 8 July 2023 and 9 June 2024')
    assert [s['house'] for s in slots]==['lok_sabha','lok_sabha']


def test_route_returns_scoped_missing_topic_without_model_call():
    from lok_sabha_rag.api.routes import synthesize as route
    from lok_sabha_rag.api.schemas import SynthesizeRequest
    from fastapi import HTTPException
    from unittest.mock import patch
    r=Mock(); r.search.return_value=[]
    with patch.object(route,'retriever',r), patch.object(route,'synthesizer') as generator:
        with pytest.raises(HTTPException) as error:
            route.synthesize(SynthesizeRequest(query=QUERY,house='both'))
    assert error.value.status_code==404
    assert 'comparison topics' in error.value.detail
    generator.generate.assert_not_called()


def test_names_are_not_satisfied_by_generic_topic_overlap():
    r,a,b,_=setup()
    wrong=replace(b,text='Otherplace school vacancies 20',subject='School vacancies')
    r.search.side_effect=[[a],[wrong]]
    r._fetch_leading_chunks.side_effect=[[a],[wrong]]
    items,_=retrieve_slots(r,QUERY,8,4,2,house='both')
    assert {i.question_id for i in items}=={'a'}


@pytest.mark.parametrize('q',['What is Kavach?', 'Compare bridge capacity in 2023 and 2024', 'Compare coverage as of 8 July 2023 and as of 9 June 2024'])
def test_unsupported_queries_leave_existing_path(q):
    assert plan_slots(q) is None
