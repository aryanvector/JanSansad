from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest

from lok_sabha_rag.core.retriever import Retriever, _extract_evidence
from lok_sabha_rag.core.scoped_retrieval import retrieve_scoped
from lok_sabha_rag.evaluation.compare_systems import load_ablation, context_support, run_retrieval


def evidence(qid,text,index=0):
    return _extract_evidence(NS(id=qid+str(index),score=.8,payload={
        'question_id':qid,'text':text,'date':'2026-03-16','lok_no':18,'session_no':7,
        'ques_no':1,'type':'UNSTARRED','source':{'chunk_index':index}}),score=.8)


def test_ablation_disables_only_named_blocks_and_does_not_rescue():
    fn,disabled=load_ablation()
    assert disabled=={'table_bonus':1,'recovery':1,'unit_carryover':1}
    good=evidence('good','PM SHRI Bihar approved outlay 1000.75 crore')
    query='Bihar PM SHRI approved outlay in the 16 March 2026 reply'
    full=Mock();full.search.side_effect=[[],[good]];full._fetch_leading_chunks.return_value=[good]
    assert retrieve_scoped(full,query,10,2,1,content_type='qa')[0]
    base=Mock();base.search.side_effect=[[],[good]]
    assert not fn(base,query,10,2,1,content_type='qa')[0]
    assert base.search.call_count==1


def test_ablation_does_not_carry_adjacent_unit_heading():
    fn,_=load_ablation()
    intro=evidence('good','PM SHRI Bihar approved outlay\n(₹ in crore)',0)
    table=evidence('good','| Approved outlay | Central share |\n| 1000.75 | 600.45 |',1)
    r=Mock();r.search.return_value=[intro];r._fetch_leading_chunks.return_value=[intro,table]
    items,_=fn(r,'Bihar PM SHRI approved outlay in the 16 March 2026 reply',10,2,2,content_type='qa')
    assert all('Source unit heading' not in c.text for c in items)


def test_quote_proxy_is_whitespace_normalized_but_reference_record_bound():
    q={'required_facts':[{'evidence':{'question_id':'one','quote':'A supported figure'}}]}
    assert context_support(q,[{'question_id':'one','chunks':[{'text':'A\n supported   figure'}]}])['coverage']==1
    assert context_support(q,[{'question_id':'another','chunks':[{'text':'A supported figure'}]}])['coverage']==0


def test_metering_is_restored_even_if_search_fails():
    base=Mock();client=base.client
    with patch.object(Retriever,'search',side_effect=RuntimeError('test failure')):
        with pytest.raises(RuntimeError):
            run_retrieval(base,{'query':'test','filters':{'house':'both','content_type':'qa'}},'base',None)
    assert base.client is client
