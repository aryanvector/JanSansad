"""Reject wrong identity, stale provenance and unsafe PDF links."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from lok_sabha_rag.core import pdf_links as p
spec=importlib.util.spec_from_file_location('matcher',ROOT/'scripts'/'match_rs_pdfs.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class PdfMatchTests(unittest.TestCase):
    def setUp(self):
        self.record={'question_id':'RS_267_313837','source_record_id':313837,'session_no':267,'ques_no':3957,'type':'UNSTARRED','date':'2025-04-04','subject':'Railway Line from Latur and Bidar to Nanded'}
        self.url='https://sansad.in/getFile/annex/267/AU3957_Spxxmp.pdf?source=pqars'
        self.official={'qslno':313837,'ses_no':267,'qno':3957,'qtype':'UNSTARRED ','adate':'2025-04-04T00:00:00','qtitle':self.record['subject'],'eng_file_dsp':self.url.replace('https://sansad.in','')}
        self.text='GOVERNMENT OF INDIA\nRAJYA SABHA\nUNSTARRED QUESTION NO.3957\nANSWERED ON 04.04.2025\n'+self.record['subject']

    def test_exact_official_identity(self):
        self.assertEqual(m.candidate(self.record,self.official),self.url)
        self.assertTrue(m.verify_text(self.text,self.record))

    def test_same_number_different_date_or_type_rejected(self):
        for key,value in [('adate','2025-04-03'),('qtype','STARRED'),('ses_no',266),('qslno',1),('qtitle','A completely different subject')]:
            row={**self.official,key:value}
            self.assertIsNone(m.candidate(self.record,row))

    def test_wrong_pdf_content_rejected(self):
        for bad in [self.text.replace('3957','3958'),self.text.replace('04.04.2025','03.04.2025'),self.text.replace('UNSTARRED','STARRED'),self.text.replace('RAJYA SABHA','LOK SABHA')]:
            self.assertFalse(m.verify_text(bad,self.record))
        self.assertFalse(m.verify_text(self.text.replace('04.04.2025','03.04.2025')+'\nStatistics as on 04.04.2025',self.record))

    def test_official_typographic_variants(self):
        for variant in [self.text.replace('RAJYA SABHA','RAJYASABHA'),self.text.replace('UNSTARRED','UN-STARRED'),self.text.replace('NO.','NO \u2013'),self.text.replace('RAJYA SABHA','RAJAY SABHA'),self.text.replace('3957','3 957').replace('04.04.2025','04 . 04 .202 5')]:
            self.assertTrue(m.verify_text(variant,self.record))

    def test_safe_url_requires_official_host_and_session(self):
        for bad in ['https://sansad.in.evil.test/getFile/annex/267/a.pdf','javascript:alert(1)',self.url.replace('/267/','/266/')]:
            self.assertFalse(m.safe_pdf(bad,267))

    def test_word_runs_preserve_numbers_and_dates(self):
        import io
        from zipfile import ZipFile
        import xml.etree.ElementTree as ET
        ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        root=ET.Element(ns+'document');body=ET.SubElement(root,ns+'body')
        for line in self.text.splitlines():
            paragraph=ET.SubElement(body,ns+'p')
            for part in (line[:len(line)//2],line[len(line)//2:]):
                run=ET.SubElement(paragraph,ns+'r');ET.SubElement(run,ns+'t').text=part
        stream=io.BytesIO()
        with ZipFile(stream,'w') as z:z.writestr('word/document.xml',ET.tostring(root))
        valid,kind=m.verify_bytes(stream.getvalue(),self.url.replace('.pdf','.docx'),self.record)
        self.assertTrue(valid);self.assertEqual(kind,'docx')

    def test_legacy_doc_is_not_mislabelled_pdf(self):
        self.assertFalse(m.safe_pdf(self.url.replace('.pdf','.docx'),267))
        self.assertTrue(m.safe_document(self.url.replace('.pdf','.docx'),267))
        self.assertFalse(m.safe_document(self.url.replace('.pdf','.doc'),267))

    def test_mapping_is_bound_to_current_payload_and_revision(self):
        payload={**self.record,'house':'rajya_sabha','source':{'dataset_revision':'pinned'}}
        entry={**self.record,'url':self.url,'title':self.record['subject'],'verified':True}
        data={'dataset':'anudit/rajyasabha-qa','dataset_revision':'pinned','links':{self.record['question_id']:entry}}
        with patch.object(p,'mapping',return_value=data):
            self.assertEqual(p.verified_pdf(payload),self.url)
            self.assertIsNone(p.verified_pdf({**payload,'date':'2025-04-03'}))
            self.assertIsNone(p.verified_pdf({**payload,'source':{'dataset_revision':'old'}}))
            self.assertIsNone(p.verified_pdf({**payload,'house':'lok_sabha'}))

    def test_missing_or_corrupt_cache_is_safe(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(p,'DATA_DIR',Path(temp)):
            self.assertEqual(p.mapping(),{})
            folder=Path(temp)/'rajya_sabha';folder.mkdir()
            (folder/'pdf-links.json').write_text('{invalid')
            self.assertEqual(p.mapping(),{})

if __name__=='__main__':unittest.main()
