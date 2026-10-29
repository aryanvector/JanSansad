"""Version isolation, retrieval and citation checks; no paid model calls."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from lok_sabha_rag.core import bill_documents as d


def record():
    return {'id':'B_example','title':'Example Telecommunications Bill, 2023','documents':[
        {'label':'As introduced','url':'https://sansad.in/getFile/BillsTexts/intro.pdf'},
        {'label':'As passed by Lok Sabha','url':'https://sansad.in/getFile/BillsTexts/passed.pdf'},
        {'label':'Gazette notification','url':'https://sansad.in/getFile/gazette.docx'}]}


def document():
    return {'bill_id':'B_example','title':'Example Telecommunications Bill, 2023','version':'introduced',
        'version_label':'As introduced','source_url':record()['documents'][0]['url'],
        'pdf_sha256':'abc','extracted_at':'2026-10-25','page_count':3,'readable_pages':2,'warnings':[],
        'pages':[{'page':1,'readable':True,'text':'Example Telecommunications Bill, 2023. Short title and extent.'},
                 {'page':2,'readable':False,'text':''},
                 {'page':3,'readable':True,'text':'3. Authorisation is required for providing telecommunication services. '*12}]}


class BillDocumentTests(unittest.TestCase):
    def test_pdf_version_and_word_document_are_distinct(self):
        self.assertEqual(d.source(record(),'introduced')['label'],'As introduced')
        self.assertEqual(d.source(record(),'ls_passed')['label'],'As passed by Lok Sabha')
        with self.assertRaises(d.DocumentError):d.source(record(),'gazette')
        with self.assertRaises(d.DocumentError):d.source(record(),'rs_passed')
        self.assertFalse(d.versions(record())[-1]['pdf_supported'])

    def test_cache_keys_separate_versions_bills_urls(self):
        a=d.folder(record(),'introduced');self.assertNotEqual(a,d.folder(record(),'ls_passed'))
        r=record();r['id']='B_other';self.assertNotEqual(a,d.folder(r,'introduced'))
        r=record();r['documents'][0]['url']+='?revision=2';self.assertNotEqual(a,d.folder(r,'introduced'))

    def test_official_redirects_reject_outside_destination_before_fetch(self):
        handler=d.OfficialRedirects()
        with self.assertRaises(d.DocumentError):handler.redirect_request(Mock(),None,302,'',{},'http://127.0.0.1/private')
        self.assertFalse(d.safe_url('https://sansad.in.evil.com/getFile/a.pdf'))
        self.assertFalse(d.safe_url('https://user@sansad.in/getFile/a.pdf'))

    def test_retrieval_preserves_physical_pdf_page_and_version(self):
        found,mode=d.retrieve(document(),'What authorisation is required for services?')
        self.assertEqual(mode,'bm25');self.assertEqual(found[0]['page'],3)
        self.assertIn('version=introduced#page=3',found[0]['pdf_url'])
        self.assertTrue(all(e['page']!=2 for e in found))

    def test_no_keyword_match_does_not_claim_absence(self):
        with patch.object(d,'prepare',return_value=document()),patch.object(d,'generate_answer') as gen:
            result=d.answer(record(),'introduced','Quantum bananas?')
        self.assertEqual(result['answer_status'],'insufficient_evidence');gen.assert_not_called()
        self.assertIn('does not prove',result['warnings'][0])

    def test_overview_is_labelled_partial(self):
        with patch.object(d,'prepare',return_value=document()):r=d.answer(record(),'introduced','Summarize the bill',False)
        self.assertEqual(r['retrieval_method'],'overview_sample')
        self.assertTrue(any('sampled' in w for w in r['warnings']))

    def test_sources_only_does_not_call_model(self):
        with patch.object(d,'prepare',return_value=document()),patch.object(d,'generate_answer') as gen:
            r=d.answer(record(),'introduced','authorisation',False)
        gen.assert_not_called();self.assertIsNone(r['answer']);self.assertEqual(r['answer_status'],'sources_only')

    def test_context_keeps_title_version_pages_and_source(self):
        data=document();found,_=d.retrieve(data,'authorisation');context=d.context_for(data,found)
        self.assertIn('ONLY version: As introduced',context);self.assertIn('PDF page 3',context)
        self.assertIn('[E1]',context);self.assertIn(data['source_url'],context)

    def test_citation_references_are_validated(self):
        with patch.object(d,'prepare',return_value=document()),patch.object(d,'generate_answer',return_value='Authorisation is required. [E1]'):
            r=d.answer(record(),'introduced','authorisation')
        self.assertEqual(r['answer_status'],'generated');self.assertEqual(r['cited_evidence'],[1])
        self.assertEqual(r['citation_check'],'reference_ids_valid')

    def test_missing_or_out_of_range_citations_withhold_answer(self):
        for text in ('Unsupported answer.','Unsupported answer [E999].','Unsupported answer [E1, E999].','Unsupported answer [E1, Q999].'):
            with patch.object(d,'prepare',return_value=document()),patch.object(d,'generate_answer',return_value=text):
                r=d.answer(record(),'introduced','authorisation')
            self.assertEqual(r['answer_status'],'citation_check_failed');self.assertIsNone(r['answer'])

    def test_model_failure_preserves_evidence_without_exposing_error(self):
        with patch.object(d,'prepare',return_value=document()),patch.object(d,'generate_answer',side_effect=RuntimeError('private-key-never-show')):
            r=d.answer(record(),'introduced','authorisation')
        self.assertEqual(r['answer_status'],'ai_unavailable');self.assertTrue(r['evidence'])
        self.assertNotIn('private-key',json.dumps(r))

    def test_cached_pdf_skips_network(self):
        with patch.object(d,'cached',return_value=document()),patch.object(d,'build_opener') as network:
            self.assertEqual(d.prepare(record(),'introduced'),document())
        network.assert_not_called()

    def test_quota_error_has_actionable_safe_message(self):
        error=RuntimeError('sensitive provider internals');error.code='credit_balance_exhausted'
        with patch.object(d,'prepare',return_value=document()),patch.object(d,'generate_answer',side_effect=error):
            result=d.answer(record(),'introduced','authorisation')
        self.assertEqual(result['ai_error'],'quota_exhausted')
        self.assertIn('credits',result['ai_message']);self.assertNotIn('sensitive',json.dumps(result))

    def test_scanned_document_is_not_indexed(self):
        response=Mock();response.url=record()['documents'][0]['url'];response.read.return_value=b'%PDF-test'
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response
        with patch.object(d,'cached',return_value=None),patch.object(d,'build_opener',return_value=opener),patch.object(d,'extract_pdf',return_value={'pages':[{'page':1,'text':'','readable':False}]}):
            with self.assertRaisesRegex(d.DocumentError,'OCR'):d.prepare(record(),'introduced')

    def test_wrong_title_is_not_cached(self):
        response=Mock();response.url=record()['documents'][0]['url'];response.read.return_value=b'%PDF-test'
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response
        with patch.object(d,'cached',return_value=None),patch.object(d,'build_opener',return_value=opener),patch.object(d,'extract_pdf',return_value={'pages':[{'page':1,'text':'Entirely unrelated maritime shipping regulations.','readable':True}]}):
            with self.assertRaisesRegex(d.DocumentError,'title'):d.prepare(record(),'introduced')

    def test_parser_timeout_has_a_clear_error(self):
        import subprocess
        with patch.object(d.subprocess,'run',side_effect=subprocess.TimeoutExpired('python',45)):
            with self.assertRaisesRegex(d.DocumentError,'45 seconds'):d.extract_pdf(b'%PDF-')


if __name__=='__main__':unittest.main()
