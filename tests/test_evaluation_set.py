from copy import deepcopy
from pathlib import Path

import pytest

from lok_sabha_rag.evaluation.validate_set import check_files, check_future, check_quote, safe_file, sha


def source_and_fact():
    text='Approved outlay was 10 crore, not a spending total.'
    source={'q':{'chunks':[{'chunk_index':0,'chunk_id':'c','text':text}]}}
    fact={'statement':'Approved outlay 10 crore.','value':10,'unit':'Rs crore',
          'evidence':{'question_id':'q','chunk_index':0,'chunk_id':'c','quote':text,'quote_sha256':sha(text)}}
    return source,fact


def test_quote_must_have_real_chunk_identity_and_exact_source_text():
    sources,fact=source_and_fact();check_quote(fact,sources)
    bad=deepcopy(fact);bad['evidence']['quote']='Spent 10 crore.';bad['evidence']['quote_sha256']=sha('Spent 10 crore.')
    with pytest.raises(ValueError,match='absent'):check_quote(bad,sources)
    bad=deepcopy(fact);bad['evidence']['chunk_id']='another'
    with pytest.raises(ValueError,match='identity'):check_quote(bad,sources)


def test_reference_quote_hash_must_match_its_stored_text():
    sources,fact=source_and_fact();fact['evidence']['quote_sha256']='wrong'
    with pytest.raises(ValueError,match='hash mismatch'):check_quote(fact,sources)


def test_numeric_reference_requires_unit_description():
    sources,fact=source_and_fact();fact['unit']=None
    with pytest.raises(ValueError,match='unit'):check_quote(fact,sources)


def test_negative_control_rechecked_against_corpus_upper_bound():
    q={'negative_basis':{'requested_date':'2027-12-31'},'required_facts':[],'evidence_groups':[],'required_record_ids':[]}
    check_future(q,{'qa':{'ls':{'date_to':'2026-03-17'}}})
    with pytest.raises(ValueError,match='date bounds'):
        check_future(q,{'qa':{'ls':{'date_to':'2028-01-01'}}})
    q['required_record_ids']=['older-source']
    with pytest.raises(ValueError,match='substitute'):
        check_future(q,{'qa':{'ls':{'date_to':'2026-03-17'}}})


def test_freeze_rejects_changes_and_path_escape(tmp_path):
    p=tmp_path/'file.txt';p.write_text('original')
    check_files(tmp_path,{'file.txt':sha('original')})
    p.write_text('changed')
    with pytest.raises(ValueError,match='changed frozen file'):check_files(tmp_path,{'file.txt':sha('original')})
    with pytest.raises(ValueError,match='escapes'):safe_file(tmp_path,'../outside.txt')
