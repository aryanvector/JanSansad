from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import pytest

from lok_sabha_rag.core.scoped_retrieval import (
    requested_answer_dates, query_plan, retrieve_scoped, scope_context,
)
from lok_sabha_rag.core.retriever import _extract_evidence, _build_filter


@pytest.mark.parametrize('query,dates', [
    ('What did the reply on 16 March 2026 report?', ['2026-03-16']),
    ('According to the answer dated 2026-03-16, what was selected?', ['2026-03-16']),
    ('Use the reply of 16.03.2026', ['2026-03-16']),
    ('Use the answer of March 16th, 2026', ['2026-03-16']),
    ('Compare replies on 3 December 2025 and 11 March 2026', ['2025-12-03','2026-03-11']),
    ('What was operational as of 28 February 2026?', []),
    ('In the answer dated 11 March 2026, give coverage as of 28 February 2026', ['2026-03-11']),
    ('What did the reply on 31 February 2026 report?', []),
    ('When did trials begin in February 2016?', []),
    ('In the 13 March 2026 reply, what did the advisory dated 28 March 2024 mean?', ['2026-03-13']),
])
def test_record_date_is_distinct_from_observation_date(query, dates):
    assert requested_answer_dates(query) == dates


def evidence(qid, text, date='2026-03-16', index=0, score=.8):
    return _extract_evidence(NS(id=f'{qid}-{index}', payload={
        'question_id':qid, 'date':date,'text':text,'lok_no':18,'session_no':7,
        'ques_no':1,'type':'UNSTARRED','source':{'chunk_index':index},
        'subject':'Education scheme'}, score=score), score=score)


def test_planner_does_not_activate_for_unscoped_or_future_asof_questions():
    assert query_plan('What is Kavach?') is None
    assert query_plan('Give exact Kavach coverage as of 31 December 2027') is None
    p=query_plan('How many children in Kallakurichi constituency in the PM POSHAN reply of 16 March 2026?')
    assert p['anchors'] == ['Kallakurichi']
    assert p['schemes'] == ['PM POSHAN']


def test_exact_date_filter_intersects_existing_filters():
    f=_build_filter(record_dates=['2026-03-16'],record_year=2026,ministry='EDUCATION',mp_names=['Member'])
    assert len([c for c in f.must if c.key=='date'])==2
    assert {'ministry','mp_names'} <= {c.key for c in f.must}


def test_matching_location_can_be_in_a_later_passage_and_budget_is_preserved():
    intro=evidence('good','PM POSHAN national programme', index=0)
    fact=evidence('good','PM POSHAN Kallakurichi constituency covered 137861 children',index=4)
    wrong=evidence('wrong','PM SHRI Kallakurichi selected schools')
    r=Mock()
    r.search.return_value=[intro,wrong]
    r._fetch_leading_chunks.side_effect=lambda **kw: [intro,fact] if kw['question_id']=='good' else [wrong]
    items,plan=retrieve_scoped(r,'In the 16 March 2026 PM POSHAN reply, how many children in Kallakurichi constituency?',4,2,1,house='lok_sabha',content_type='qa',ministry='EDUCATION')
    assert len(items)==1 and items[0].chunk_index==4
    assert not plan['missing_dates'] and not plan['missing_anchors']
    kwargs=r.search.call_args.kwargs
    assert kwargs['record_dates']==['2026-03-16']
    assert kwargs['house']=='lok_sabha' and kwargs['ministry']=='EDUCATION'
    assert r._fetch_leading_chunks.call_args.kwargs['c']==64


def test_wrong_date_is_not_substituted():
    r=Mock()
    r.search.return_value=[evidence('old','Kavach commissioned',date='2026-02-11')]
    items,plan=retrieve_scoped(r,'What did the Kavach answer on 11 March 2026 report?',45,10,2,content_type='qa')
    assert not items and plan['missing_dates']==['2026-03-11']
    r._fetch_leading_chunks.assert_not_called()


def test_two_requested_dates_are_both_reserved_before_n_trimming():
    a=evidence('a','Kavach commissioned route km',date='2025-12-03')
    b=evidence('b','Kavach commissioned route km',date='2026-03-11')
    r=Mock()
    r.search.side_effect=lambda **kw:[a] if kw['record_dates']==['2025-12-03'] else [b]
    r._fetch_leading_chunks.side_effect=lambda **kw:[a] if kw['question_id']=='a' else [b]
    items,plan=retrieve_scoped(r,'Compare Kavach replies on 3 December 2025 and 11 March 2026',5,2,2,content_type='qa')
    assert len(items)==2 and not plan['missing_dates']
    assert sum(c.kwargs['top_k'] for c in r.search.call_args_list)==5


def test_incompatible_scheme_or_location_is_not_used():
    r=Mock()
    r.search.return_value=[evidence('bad','PM POSHAN Tamil Nadu school meals')]
    r._fetch_leading_chunks.return_value=r.search.return_value
    items,plan=retrieve_scoped(r,'What does the Bihar PM SHRI reply of 16 March 2026 say?',45,10,2,content_type='qa')
    assert not items and plan['missing_anchors']==['Bihar']


def test_debates_and_year_comparisons_keep_existing_paths():
    r=Mock()
    assert retrieve_scoped(r,'Compare Kavach in 2025 and 2026',45,10,2,content_type='qa') is None
    assert retrieve_scoped(r,'Bihar PM SHRI answer 16 March 2026',45,10,2,content_type='debate') is None
    r.search.assert_not_called()


def test_scope_note_never_infers_user_error_from_missing_evidence():
    p=query_plan('What did the Kavach answer on 11 March 2026 say?')
    p.update(missing_dates=['2026-03-11'],missing_anchors=[])
    assert 'Never call the user date wrong' in scope_context(p)


def test_empty_scope_returns_clear_failure_without_generation():
    from lok_sabha_rag.api.routes import synthesize as route
    from lok_sabha_rag.api.schemas import SynthesizeRequest
    from fastapi import HTTPException
    p=query_plan('What did the Kavach answer on 11 March 2026 say?')
    p.update(missing_dates=['2026-03-11'],missing_anchors=[])
    generator=Mock()
    with patch.object(route,'retrieve_scoped',return_value=([],p)),patch.object(route,'synthesizer',generator):
        with pytest.raises(HTTPException) as error:
            route.synthesize(SynthesizeRequest(query='What did the Kavach answer on 11 March 2026 say?'))
    assert error.value.status_code==404 and 'does not establish' in error.value.detail
    generator.generate.assert_not_called()


def test_no_match_rescue_simplifies_topic_without_relaxing_source_filters():
    bad = evidence('bad', 'Unrelated scholarship programme')
    good = evidence('good', 'PM SHRI Bihar approved outlay 1000.75 crore')
    r = Mock()
    r.search.side_effect = [[bad], [good]]
    r._fetch_leading_chunks.side_effect = lambda **kw: [good] if kw['question_id'] == 'good' else [bad]
    items, plan = retrieve_scoped(r,
        'According to the Lok Sabha reply on 16 March 2026, what was the Bihar PM SHRI approved outlay for FY 2025-26? Is it actual expenditure?',
        50, 10, 1, house='lok_sabha', content_type='qa', ministry='EDUCATION')
    assert items and items[0].question_id == 'good'
    assert plan['rescue_queries'] == ['Bihar PM SHRI']
    assert plan['retrieval_passes'] == 2
    second = r.search.call_args_list[1].kwargs
    assert second['record_dates'] == ['2026-03-16']
    assert second['house'] == 'lok_sabha' and second['ministry'] == 'EDUCATION'
    assert second['top_k'] == 50
    assert len(items) <= 50


def test_rescue_never_substitutes_wrong_date_or_wrong_place():
    old = evidence('old', 'PM SHRI Bihar outlay', date='2025-03-16')
    other = evidence('other', 'PM SHRI Kerala outlay')
    r = Mock()
    r.search.side_effect = [[other], [old]]
    r._fetch_leading_chunks.return_value = [other]
    items, plan = retrieve_scoped(r, 'Bihar PM SHRI outlay in the 16 March 2026 reply', 10, 2, 1, content_type='qa')
    assert not items and plan['missing_anchors'] == ['Bihar']
    assert r.search.call_count == 2


def test_rescue_does_not_rerun_successful_search_or_fetch_duplicate_records():
    good = evidence('good', 'PM SHRI Bihar approved outlay 1000.75 crore')
    r = Mock()
    r.search.return_value = [good]
    r._fetch_leading_chunks.return_value = [good]
    items, plan = retrieve_scoped(r, 'Bihar PM SHRI outlay in the 16 March 2026 reply', 10, 2, 1, content_type='qa')
    assert items and plan['retrieval_passes'] == 1
    assert r.search.call_count == r._fetch_leading_chunks.call_count == 1


def test_numeric_table_selected_with_source_unit_under_one_passage_budget():
    intro = evidence('good', 'PM SHRI Bihar reply: approved funds for FY 2025-26 are as follows.\n(₹ in crore)', index=0)
    table = evidence('good', '| Financial Year | Approved PAB outlay | Central Share |\n| 2025-26 | 1000.75 | 600.45 |', index=1)
    r = Mock()
    r.search.return_value = [intro]
    r._fetch_leading_chunks.return_value = [intro, table]
    items, plan = retrieve_scoped(r, 'Bihar PM SHRI approved outlay for FY 2025-26 in the 16 March 2026 reply', 10, 2, 1, content_type='qa')
    assert len(items) == 1 and items[0].chunk_index == 1
    assert '1000.75' in items[0].text and '(₹ in crore)' in items[0].text
    assert 'immediately preceding passage' in items[0].text


def test_table_unit_is_not_inferred_from_other_record_or_nonadjacent_text():
    intro = evidence('good', 'PM SHRI Bihar: details in financial table.', index=0)
    table = evidence('good', '| Financial Year | Approved outlay |\n| 2025-26 | 1000.75 |', index=1)
    r = Mock()
    r.search.return_value = [intro]
    r._fetch_leading_chunks.return_value = [intro, table]
    items, _ = retrieve_scoped(r, 'Bihar PM SHRI approved outlay in the 16 March 2026 reply', 10, 2, 1, content_type='qa')
    assert items[0].chunk_index == 1 and 'crore' not in items[0].text
