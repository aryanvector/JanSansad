"""Resolver accepts only indexed IDs and preserves fallback on source failure."""
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from urllib.error import URLError
from lok_sabha_rag.api.routes import rs_documents as r

class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.row=dict(question_id='RS_K_test',session_no=243,ques_no=1857,type='UNSTARRED',date='2017-08-01',subject='GST',source_record_id=1,source_dataset='rajanand/rajyasabha',dataset_revision='kaggle-version-4')

    def test_unindexed_record_is_not_looked_up(self):
        with patch.object(r,'find_record',return_value=None),patch.object(r,'urlopen') as request:
            with self.assertRaises(HTTPException) as error:r.resolve(r.DocumentRequest(question_id='RS_K_unknown'))
            self.assertEqual(error.exception.status_code,404);request.assert_not_called()

    def test_cached_verified_word_is_returned_as_word(self):
        url='https://sansad.in/getFile/annex/243/Au1857.docx?source=pqars'
        with patch.object(r,'find_record',return_value=self.row),patch.object(r,'mapping',return_value={'links':{'RS_K_test':{'url':url,'format':'docx'}}}),patch.object(r,'verified_document',return_value=url),patch.object(r,'urlopen') as request:
            result=r.resolve(r.DocumentRequest(question_id='RS_K_test'))
            self.assertEqual(result['format'],'docx');request.assert_not_called()

    def test_temporary_outage_is_not_cached_as_missing_document(self):
        with patch.object(r,'find_record',return_value=self.row),patch.object(r,'mapping',return_value={}),patch.object(r,'urlopen',side_effect=URLError('offline')),patch.object(r,'store_result') as store:
            with self.assertRaises(HTTPException) as error:r.resolve(r.DocumentRequest(question_id='RS_K_test'))
            self.assertEqual(error.exception.status_code,503);store.assert_not_called()

    def test_raw_url_is_rejected(self):
        with self.assertRaises(ValueError):r.DocumentRequest(question_id='https://evil.test/file')

if __name__=='__main__':unittest.main()
