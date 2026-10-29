from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest

from lok_sabha_rag.core.temporal_retrieval import (
    comparison_years, dates_in_year, balanced_groups, retrieve_comparison,
    period_coverage, coverage_context, comparison_search_query,
)
from lok_sabha_rag.core.retriever import _build_filter
from lok_sabha_rag.core import kaggle_store
import json
import sqlite3


@pytest.mark.parametrize('query,expected', [
    ('Compare Kavach progress in 2025 and 2026', [2025, 2026]),
    ('Kavach 2026 vs 2025', [2025, 2026]),
    ('Show changes from 2024 to 2026', [2024, 2025, 2026]),
    ('2025 aur 2026 mein Kavach ki tulna karo', [2025, 2026]),
    ('2025 और 2026 की तुलना करो', [2025, 2026]),
    ('What happened in 2025?', []),
    ('Compare FY 2024-25 and 2025-26', []),
    ('Compare 2024-25 and 2025-26', []),
    ('Compare financial years 2024 and 2025', []),
    ('Compare progress from 2009 to 2026', []),
    ('Compare 2026 to 2024', []),
    ('When were 2016 trials and 2020 adoption?', []),
    ('Compare the 2016 trials with 2020 adoption', []),
    ('Compare answers dated 2025-01-01 and 2026-01-01', []),
])
def test_conservative_year_detection(query, expected):
    assert comparison_years(query) == expected


def test_exact_dates_and_existing_filters_are_combined():
    dates = dates_in_year(2024)
    assert len(dates) == 366 and '2024-02-29' in dates
    assert dates[0] == '2024-01-01' and dates[-1] == '2024-12-31'
    f = _build_filter(record_year=2024, ministry='RAILWAYS', mp_names=['Member'], lok=18)
    assert {x.key for x in f.must} == {'date', 'ministry', 'mp_names', 'lok_no'}
    assert next(x.match.any for x in f.must if x.key == 'date') == dates
    with pytest.raises(ValueError):
        dates_in_year(9999)


def item(year, ident):
    return NS(date=f'{year}-04-04', house='lok_sabha', question_id=ident, chunk_id=ident)


def test_retrieval_splits_m_and_preserves_user_filters():
    r = Mock()
    r.search.side_effect = lambda **kw: [item(kw['record_year'], f"{kw['record_year']}-{n}") for n in range(kw['top_k'])]
    result, years = retrieve_comparison(r, 'Compare 2025 vs 2026', 5, house='both', content_type='qa', ministry='RAILWAYS')
    assert years == [2025, 2026] and len(result) == 5
    assert [c.kwargs['top_k'] for c in r.search.call_args_list] == [3, 2]
    assert all(c.kwargs['ministry'] == 'RAILWAYS' for c in r.search.call_args_list)
    assert all(c.kwargs['house'] == 'both' for c in r.search.call_args_list)
    assert [x.date[:4] for x in result] == ['2025', '2026', '2025', '2026', '2025']


def test_subquery_keeps_topic_not_missing_evidence_instructions():
    query = 'Compare the Kavach deployment figures reported in parliamentary answers in 2025 versus 2027. If either year has no source, explicitly identify that gap.'
    assert comparison_search_query(query) == 'Kavach deployment figures'
    assert comparison_search_query('Compare 2025 and 2026') == 'Compare 2025 and 2026'


def test_missing_year_is_not_backfilled_from_another_year():
    r = Mock()
    r.search.side_effect = lambda **kw: [item(2025, 'old')] if kw['record_year'] == 2025 else [item(2024, 'wrong-date')]
    result, years = retrieve_comparison(r, 'Compare 2025 and 2027', 10, content_type='qa')
    coverage = period_coverage(result, years)
    assert coverage['missing_years'] == [2027]
    assert len(result) == 1
    assert '2027' in coverage_context(coverage)


def test_n_trimming_reserves_sources_for_each_requested_year():
    groups = [item(2025, 'a'), item(2025, 'b'), item(2026, 'c')]
    selected = balanced_groups(groups, [2025, 2026], 2)
    assert [g.question_id for g in selected] == ['a', 'c']
    assert not period_coverage(selected, [2025, 2026])['missing_years']


def test_small_budget_is_explicitly_incomplete_and_never_calls_zero_limit():
    r = Mock()
    r.search.return_value = [item(2025, 'a')]
    result, years = retrieve_comparison(r, 'Compare 2025 vs 2026', 1, content_type='qa')
    assert r.search.call_count == 1
    assert period_coverage(result, years)['missing_years'] == [2026]


def test_noncomparisons_and_debates_use_the_original_path():
    for query, content in [('Kavach kya hai?', 'qa'), ('Compare 2025 and 2026', 'debate'), ('Compare 2025 and 2026', 'all')]:
        r = Mock()
        result, years = retrieve_comparison(r, query, 45, content_type=content)
        assert years == []
        r.search.assert_called_once_with(query=query, top_k=45, content_type=content)


def test_historical_lexical_store_filters_real_record_dates(tmp_path):
    db_path = tmp_path / 'records.db'
    db = sqlite3.connect(db_path)
    db.execute('CREATE TABLE records(question_id TEXT, record TEXT)')
    db.execute('CREATE VIRTUAL TABLE docs USING fts5(subject,text)')
    for year in [2016, 2017]:
        db.execute('INSERT INTO records VALUES (?,?)', (str(year), json.dumps({'question_id': str(year), 'date': f'{year}-04-04'})))
        db.execute('INSERT INTO docs VALUES (?,?)', ('Railway', 'Kavach safety'))
    db.commit()
    db.close()
    with patch.object(kaggle_store, 'path', return_value=db_path):
        assert [x['question_id'] for x in kaggle_store.search('Kavach', record_year=2017)] == ['2017']
        assert kaggle_store.search('Kavach', record_year=2026) == []


def test_coverage_is_not_labelled_as_statistic_comparability():
    text = coverage_context(period_coverage([item(2025, 'a'), item(2026, 'b')], [2025, 2026]))
    assert 'Publication/answer dates are not observation dates' in text
    assert 'do not by themselves prove' in text


def test_shared_client_query_accumulator_is_not_used_concurrently():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    import time
    from lok_sabha_rag.core.retriever import Retriever

    r = Retriever.__new__(Retriever)
    tracker = {'active': 0, 'maximum': 0}
    tracker_lock = Lock()
    def query(**kwargs):
        with tracker_lock:
            tracker['active'] += 1
            tracker['maximum'] = max(tracker['maximum'], tracker['active'])
        time.sleep(.02)
        with tracker_lock:
            tracker['active'] -= 1
        return NS(points=[])
    r.client = Mock()
    r.client.query_points.side_effect = query
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(r._query_points, query='text') for _ in range(2)]
        for future in futures:
            future.result()
    assert tracker['maximum'] == 1


def test_synthesis_exposes_coverage_and_passes_the_selected_years_to_context():
    from lok_sabha_rag.api.routes import synthesize as route
    from lok_sabha_rag.api.schemas import SynthesizeRequest
    from lok_sabha_rag.core.retriever import Retriever, _extract_evidence

    r = Retriever.__new__(Retriever)
    def search(**kwargs):
        year = kwargs['record_year']
        return [_extract_evidence(NS(id=str(year), payload={
            'question_id': str(year), 'date': f'{year}-04-04',
            'text': f'Dated evidence for {year}', 'source': {'chunk_index': 0},
            'ques_no': 1, 'lok_no': 18, 'session_no': 1,
        }), score=.9)]
    generator = Mock()
    generator.generate.return_value = 'Compared sources [Q1][Q2].'
    with patch.object(r, 'search', side_effect=search), patch.object(r, '_count_total_chunks', return_value=1), patch.object(r, '_fetch_leading_chunks', return_value=[]), patch.object(route, 'retriever', r), patch.object(route, 'synthesizer', generator):
        result = route.synthesize(SynthesizeRequest(query='Compare parliamentary answers in 2025 and 2026', top_n=2))
    assert result.period_coverage['records_in_context'] == {'2025': 1, '2026': 1}
    assert not result.period_coverage['missing_years']
    assert 'COMPARISON SOURCE COVERAGE' in generator.generate.call_args.kwargs['context']
