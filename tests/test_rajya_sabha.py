"""Cross-House isolation and source attribution, with no network or paid LLM."""
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace as NS
from lok_sabha_rag.core.retriever import Retriever, _extract_evidence,fuse_ranked
from lok_sabha_rag.pipeline.import_rajya_sabha import normalize
from lok_sabha_rag.api.schemas import SearchRequest

def point(qid, house, score):
    return NS(id=qid, score=score, payload=dict(question_id=qid, house=house,
        session_no=243, ques_no=1, text='Official answer text', date='2017-08-11',
        source={'chunk_index':0,'source_url':'https://www.kaggle.com/datasets/rajanand/rajyasabha'}))

class CrossHouseTests(unittest.TestCase):
    def setUp(self):
        patcher=patch('lok_sabha_rag.core.retriever.kaggle_store.search',return_value=[])
        patcher.start();self.addCleanup(patcher.stop)
    def test_retriever_loads_activated_collection(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'rajya_sabha'; folder.mkdir()
            (folder/'manifest.json').write_text(json.dumps({'collection':'rajya_sabha_hf_questions_v1'}))
            with patch('lok_sabha_rag.core.retriever.DATA_DIR',Path(temp)), patch('lok_sabha_rag.core.retriever.QdrantClient'):
                r=Retriever()
                self.assertEqual(r._record_collection('RS_267_123'),'rajya_sabha_hf_questions_v1')
                self.assertEqual(r._record_collection('17_1_1_UNSTARRED'),r.collection)

    def retriever(self):
        r=Retriever.__new__(Retriever)
        r.client=Mock(); r.client.collection_exists.return_value=True
        r.collection='lok_sabha_questions'; r.rs_collection='rajya_sabha_questions'; r.model='BAAI/bge-small-en-v1.5'
        r.client.query_points.side_effect=lambda **kw: NS(points=[point('RS_243_1','rajya_sabha',.9)] if kw['collection_name']==r.rs_collection else [point('17_1_1_UNSTARRED','lok_sabha',.8)])
        return r

    def test_default_keeps_lok_sabha(self):
        r=self.retriever(); result=r.search('education')
        self.assertEqual([x.house for x in result],['lok_sabha'])
        self.assertEqual(r.client.query_points.call_count,1)

    def test_rajya_only_uses_separate_collection(self):
        r=self.retriever(); result=r.search('education',house='rajya_sabha')
        self.assertEqual(result[0].house,'rajya_sabha')
        self.assertEqual(r.client.query_points.call_args.kwargs['collection_name'],r.rs_collection)
        self.assertEqual(r.client.query_points.call_args.kwargs['using'],'fast-bge-small-en-v1.5')

    def test_both_merge_rank_and_limit(self):
        r=self.retriever(); result=r.search('education',top_k=1,house='both')
        self.assertEqual(len(result),1); self.assertEqual(result[0].house,'rajya_sabha')
        self.assertEqual(r.client.query_points.call_count,2)

    def test_record_fetch_routes_to_correct_house(self):
        r=self.retriever(); r.client.scroll.return_value=([point('RS_243_1','rajya_sabha',0)],None)
        r._fetch_leading_chunks(2,question_id='RS_243_1')
        self.assertEqual(r.client.scroll.call_args.kwargs['collection_name'],r.rs_collection)

    def test_context_preserves_house_date_and_source(self):
        r=self.retriever(); item=_extract_evidence(point('RS_243_1','rajya_sabha',.9))
        groups=r.group_evidence([item]); text=r.build_context_grouped(groups)
        self.assertEqual(groups[0].source_url,item.source_url)
        self.assertIn('Rajya Sabha',text); self.assertIn('2017-08-11',text)
        self.assertIn('kaggle.com',text)

    def test_rs_does_not_expose_unverified_payload_pdf(self):
        source=point('RS_267_fake','rajya_sabha',.9)
        source.payload['source']['pdf_url']='https://sansad.in/getFile/unverified.pdf'
        self.assertIsNone(_extract_evidence(source).pdf_url)
        source.payload['house']='lok_sabha'
        self.assertEqual(_extract_evidence(source).pdf_url,'https://sansad.in/getFile/unverified.pdf')

    def test_missing_rs_collection_does_not_break_both(self):
        r=self.retriever(); r.client.collection_exists.return_value=False
        self.assertEqual(len(r.search('health',house='both')),1)

    def test_reject_invalid_house(self):
        with self.assertRaises(ValueError): SearchRequest(query='x',house='unknown')

    def test_rank_fusion_deduplicates_cross_source_questions_and_chunks(self):
        hf=_extract_evidence(point('RS_243_1','rajya_sabha',.9))
        other=point('RS_K_other','rajya_sabha',.1)
        kg=_extract_evidence(other)
        result=fuse_ranked([[hf,hf],[kg]],10)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].question_id,hf.question_id)
        self.assertEqual(result[0].retrieval_method,'rank_fusion')
        self.assertAlmostEqual(result[0].score,2/61)

    def test_reject_missing_answer_and_mismatched_date(self):
        base=dict(english='Question only '*30, adate='2017-08-11', qslno=1,ses_no=243)
        self.assertIsNone(normalize(base))
        base['english']='ANSWERED ON 10.08.2017\nANSWER\n'+'Details '*30
        self.assertIsNone(normalize(base))
        base['english']='ANSWERED ON 11.08.2017\nANSWER\n'+'Details '*30
        self.assertEqual(normalize(base)['question_id'],'RS_243_1')

if __name__ == '__main__': unittest.main()
