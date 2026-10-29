"""Archive range/type isolation, distinct debates and honest transcript status."""
import importlib.util
import sys
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
if (ROOT/'scripts/import_rs_debates.py').exists():script=ROOT/'scripts/import_rs_debates.py'
else:script=Path('/tmp/import_rs_debates.py')
spec=importlib.util.spec_from_file_location('importer',script);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
from lok_sabha_rag.core import debate_store as d
from lok_sabha_rag.core.retriever import Retriever,_extract_evidence,fuse_ranked
from lok_sabha_rag.api.schemas import SearchRequest

class DebateTests(unittest.TestCase):
    def setUp(self):
        self.url='https://bucketapi.rajyasabha.digital/public-bucket/rsdebate/assetstore/12/file?response-content-disposition=inline%3Bfilename%3D%22ID_267_04042025_p1.pdf%22'
        self.raw=dict(resourceId=1,date='2025-04-04',type='Part 2 (Other Than Question And Answer)',sessionNo=267,title='Education policy discussion',members=['A'],files=[self.url],debateTitleSubject='DISCUSSION',pageNoFromTo='1-2')
        self.row=m.normalize(self.raw,2009,2026)[0]

    def test_range_and_qa_are_excluded(self):
        self.assertIsNotNone(self.row)
        for changes in ({'date':'2008-12-31'},{'type':'Part 1 (Question And Answer)'},{'questionNo':1},{'title':None}):
            self.assertIsNone(m.normalize({**self.raw,**changes},2009,2026)[0])

    def test_unsafe_document_hosts_rejected(self):
        for url in ['https://bucketapi.rajyasabha.digital.evil.test/file.pdf','http://sansad.in/getFile/a.pdf','https://sansad.in/admin/file.pdf']:
            self.assertFalse(d.safe_url(url));self.assertFalse(m.safe_url(url))

    def test_same_date_distinct_debates_do_not_collapse(self):
        other={**self.row,'question_id':'RS_D_2','subject':'Another discussion'}
        items=[_extract_evidence(NS(id=r['question_id'],payload=d.payload(r))) for r in (self.row,other)]
        fused=fuse_ranked([items],10)
        self.assertEqual(len(fused),2)
        self.assertTrue(all(x.content_type=='debate' for x in fused))

    def test_debate_filter_never_queries_qa(self):
        r=Retriever.__new__(Retriever);r.client=Mock();r.collection='ls';r.rs_collection='rs';r.model='BAAI/bge-small-en-v1.5'
        with patch.object(d,'search',return_value=[self.row]),patch('lok_sabha_rag.core.retriever.kaggle_store.search') as kg:
            result=r.search('education',house='rajya_sabha',content_type='debate')
        self.assertEqual(result[0].transcript_status,'metadata_only');r.client.query_points.assert_not_called();kg.assert_not_called()

    def test_group_context_preserves_transcript_and_participants(self):
        r=Retriever.__new__(Retriever)
        item=_extract_evidence(NS(id='RS_D_1',payload=d.payload(self.row)))
        with patch.object(d,'get_record',return_value=self.row),patch.object(d,'transcript',return_value={'status':'extracted','text':'A: The education discussion is recorded here. '*20}):
            groups=r.group_evidence([item],chunks_per_question=2)
        context=r.build_context_grouped(groups)
        self.assertIn('Content type: debate',context);self.assertIn('Participants listed',context)
        self.assertIn('transcript status: extracted',context)

    def test_unavailable_transcript_is_not_fabricated(self):
        with patch.object(d,'urlopen',side_effect=TimeoutError()):
            result=d.transcript(self.row)
        self.assertEqual(result['status'],'unavailable');self.assertIn('METADATA ONLY',result['text'])

    def test_invalid_content_type_rejected(self):
        with self.assertRaises(ValueError):SearchRequest(query='x',content_type='speeches-guessed')

if __name__=='__main__':unittest.main()
