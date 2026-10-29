import json
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest

from lok_sabha_rag.core import coverage_inventory as c


def test_record_dates_do_not_turn_invalid_values_into_coverage():
    result = c.dated(['2026-03-16', '2025-02-11', None, '2026-02-31', 'not-a-date'])
    assert result['date_from'] == '2025-02-11' and result['date_to'] == '2026-03-16'
    assert result['years'] == {'2025': 1, '2026': 1}
    assert result['undated_records'] == 3


def test_catalogue_summary_uses_rows_not_manifest_claims(tmp_path):
    dbpath = tmp_path/'records.db'
    with sqlite3.connect(dbpath) as db:
        db.execute('CREATE TABLE records(record TEXT)')
        db.executemany('INSERT INTO records VALUES(?)', [(json.dumps({'date': d}),) for d in ['2009-11-20', '2017-08-11']])
    result = c.database_summary(dbpath, json_date=True)
    assert result['records'] == 2 and result['date_to'] == '2017-08-11'
    assert c.database_summary(tmp_path/'missing.db')['status'] == 'unavailable'


def test_exact_index_ids_distinguish_records_chunks_and_metadata(tmp_path):
    dbpath = tmp_path/'metadata.db'
    with sqlite3.connect(dbpath) as db:
        db.execute('CREATE TABLE questions(lok_no,session_no,ques_no,type,date)')
        db.executemany('INSERT INTO questions VALUES(?,?,?,?,?)', [(18,7,1,'UNSTARRED','2026-03-16'), (18,7,2,'UNSTARRED','2026-03-17')])
    client = Mock()
    client.get_collection.return_value = NS(points_count=3)
    client.facet.return_value = NS(hits=[NS(value='18_7_1_UNSTARRED',count=3)])
    client.scroll.return_value = ([NS(payload={'question_id':'RS_1','date':'2025-04-04'}), NS(payload={'question_id':'RS_1','date':'2025-04-04'})], None)
    r = NS(client=client, collection='ls', rs_collection='rs')
    with patch.object(c, 'METADATA_DB_PATH', dbpath):
        ls, rs = c.indexed_qa(r)
    assert ls['records'] == 1 and ls['chunks'] == 3
    assert ls['metadata_records'] == 2 and ls['metadata_without_index'] == 1
    assert rs['records'] == 1 and rs['chunks'] == 2
    assert ls['date_to'] == '2026-03-16'  # Excludes unindexed newer metadata.


def test_incomplete_facet_is_not_reported_as_complete_inventory():
    client = Mock()
    client.get_collection.return_value = NS(points_count=10)
    client.facet.return_value = NS(hits=[NS(value='one', count=3)])
    with pytest.raises(ValueError, match='every indexed chunk'):
        c.indexed_qa(NS(client=client, collection='ls'))


def test_missing_or_invalid_snapshot_is_unknown_not_zero_coverage(tmp_path):
    with patch.object(c, 'DATA_DIR', tmp_path):
        assert c.snapshot()['status'] == 'not_audited'
        c.path().write_text('broken')
        assert c.snapshot()['qa'] == {}


def test_legacy_total_counts_both_houses_not_only_rs():
    from lok_sabha_rag.api.routes import corpus
    inventory = {'status':'ready', 'qa':{'ls':{'records':10}, 'rs':{'records':4}},
                 'debate_catalogues':{'ls':{'records':20}, 'rs':{'records':7}}}
    with patch.object(corpus, 'rs_manifest', return_value={'status':'not_imported','records':0}), \
         patch.object(corpus.kaggle_store, 'manifest', return_value={}), \
         patch.object(corpus, 'mapping', return_value={}), \
         patch.object(corpus.debate_store, 'manifest', return_value={}), \
         patch.object(corpus.debate_fulltext, 'coverage', return_value={}), \
         patch.object(corpus.coverage_inventory, 'snapshot', return_value=inventory):
        result = corpus.coverage()
    assert result['all_records'] == 41
    assert 'not all full text' in result['all_records_basis']
