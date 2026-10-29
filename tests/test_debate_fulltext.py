import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from lok_sabha_rag.core import debate_fulltext as f,debate_store as d,ls_debate_documents as ls
from lok_sabha_rag.core.retriever import Retriever,_extract_evidence

script=Path(__file__).parents[1]/'scripts'/'import_ls_debates.py'
if not script.exists():script=Path('/tmp/import_ls_debates.py')
spec=importlib.util.spec_from_file_location('ls_importer',script);imp=importlib.util.module_from_spec(spec);spec.loader.exec_module(imp)

def row(house='rajya_sabha',qid='RS_D_123'):
    return dict(question_id=qid,house=house,lok_no=18 if house=='lok_sabha' else None,session_no=8,
        date='2025-04-04',subject='General discussion',content_type='debate',type='DEBATE',ques_no=None,
        debate_category='Discussion',mp_names=['Member A'],ministry='Education',original_pages='',
        source_pdf_url='https://elibrary.sansad.in/server/api/core/bitstreams/123/content',source_url='https://sansad.in/ls/debates/digitized')

class FulltextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(f,'root',return_value=Path(self.temp.name));p.start();self.addCleanup(p.stop)
    def test_body_only_match_not_in_title(self):
        f.save(row(),{'status':'extracted','text':'Scholarships for Sanskrit students were discussed. '*20})
        found=f.search('scholarships');self.assertEqual(len(found),1)
        self.assertNotIn('scholarships',found[0]['subject'].lower());self.assertIn('Scholarships',found[0]['_matched_text'])
    def test_house_lok_and_participant_filters(self):
        for r in (row(),row('lok_sabha','LS_D_123')):f.save(r,{'status':'extracted','text':'Scholarships for students. '*20})
        self.assertEqual(len(f.search('scholarships',house='both')),2)
        self.assertEqual(f.search('scholarships',house='lok_sabha')[0]['house'],'lok_sabha')
        self.assertEqual(len(f.search('scholarships',lok=18)),1)
        self.assertEqual(f.search('scholarships',session=99),[])
        self.assertEqual(f.search('scholarships',mp_names=['Unknown']),[])
    def test_reindex_replaces_chunks_without_duplicates(self):
        f.save(row(),{'status':'extracted','text':'scholarships '*100})
        f.save(row(),{'status':'extracted','text':'railways '*100})
        self.assertEqual(f.search('scholarships'),[]);self.assertEqual(len(f.search('railways')),1)
        self.assertEqual(f.coverage()['houses']['rajya_sabha']['indexed'],1)
    def test_failed_extraction_is_not_searchable(self):
        f.save(row(),{'status':'pdf_only','text':'Scholarships should not be indexed from a failure.'})
        self.assertEqual(f.search('Scholarships'),[])
        self.assertEqual(f.coverage()['houses']['rajya_sabha']['indexed'],0)
    def test_search_string_is_not_sql(self):
        f.save(row(),{'status':'extracted','text':'scholarships '*100})
        f.search('" OR 1=1; DROP TABLE documents; --');self.assertIsNotNone(f.get('RS_D_123'))
    def test_payload_keeps_matched_chunk(self):
        f.save(row(),{'status':'extracted','text':'opening '*400+'rarekeyword '*100})
        found=f.search('rarekeyword')[0];p=d.payload(found)
        self.assertEqual(p['transcript_status'],'indexed_text');self.assertIn('rarekeyword',p['text']);self.assertGreater(p['source']['chunk_index'],0)
    def test_group_preserves_match_instead_of_document_opening(self):
        f.save(row(),{'status':'extracted','text':'opening '*400+'rarekeyword '*100})
        r=f.search('rarekeyword')[0];item=_extract_evidence(NS(id=r['question_id'],payload=d.payload(r)))
        retriever=Retriever.__new__(Retriever)
        with patch.object(d,'transcript',side_effect=AssertionError('must preserve indexed match')):
            groups=retriever.group_evidence([item],chunks_per_question=2)
        self.assertIn('rarekeyword',groups[0].chunks[0].text);self.assertIn('indexed_text',retriever.build_context_grouped(groups))
    def test_ls_normalization_and_qa_exclusion(self):
        md={'dc.type':[{'value':'Part 2(Other than Questions And Answers)'}],'dc.title':[{'value':'A debate'}],
            'dc.date.issued':[{'value':'2026-08-03'}],'dc.identifier.loksabhanumber':[{'value':'18'}],
            'dc.identifier.sessionnumber':[{'value':'VIII'}]}
        obj={'uuid':'71ebbd4e-87cb-4263-947b-335d50ec153c','metadata':md}
        r,_=imp.normalize(obj,2009,2026);self.assertEqual(r['session_no'],8);self.assertEqual(r['house'],'lok_sabha')
        md['dc.identifier.questionnumber']=[{'value':'99'}];self.assertIsNone(imp.normalize(obj,2009,2026)[0])
    def test_ls_document_urls_are_restricted(self):
        self.assertTrue(ls.safe_url('https://elibrary.sansad.in/server/api/core/bitstreams/abc/content'))
        for u in ('https://elibrary.sansad.in.evil.org/server/api/core/x','http://elibrary.sansad.in/server/api/core/x','https://elibrary.sansad.in/admin'):
            self.assertFalse(ls.safe_url(u))

    def test_rs_adjacent_speeches_are_excluded(self):
        import sqlite3
        path=Path(self.temp.name)/'titles.db'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE records(subject,date,question_id)')
            db.execute('INSERT INTO records VALUES(?,?,?)',('Next debate','2025-04-04','RS_D_other'))
        text='Previous speaker talks about mangroves. General discussion\nTarget speech on scholarships. Next debate\nUnrelated next speech.'
        with patch.object(d,'connection',side_effect=lambda:sqlite3.connect(path)):
            scoped=d.bound_rs_text(row(),{'status':'extracted','text':text})
        self.assertIn('scholarships',scoped['text']);self.assertNotIn('mangroves',scoped['text']);self.assertNotIn('Unrelated',scoped['text'])

    def test_unverified_heading_does_not_become_retrievable_speech(self):
        result=d.bound_rs_text(row(),{'status':'extracted','text':'Only neighbouring speeches are present here.'})
        self.assertEqual(result['status'],'scope_unverified')

if __name__=='__main__':unittest.main()
