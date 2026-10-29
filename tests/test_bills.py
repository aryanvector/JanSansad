"""Bill identity, status semantics and document safety without network calls."""
import importlib.util
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from lok_sabha_rag.core import bill_store as store

spec=importlib.util.spec_from_file_location('import_bills',Path(__file__).parents[1]/'scripts'/'import_bills.py')
importer=importlib.util.module_from_spec(spec);spec.loader.exec_module(importer)


def raw(**kwargs):
    return dict(billName='Example Bill, 2023',billNumber='12',billYear=2023,
                billIntroducedInHouse='Rajya Sabha',billIntroducedDate='2023-08-10 00:00:00.0',
                billType='Government',status='Pending',**kwargs)


class BillTests(unittest.TestCase):
    def test_source_dates_and_missing_dates(self):
        r=importer.normalize(raw(billAssentedDate='28/12/2023'))
        self.assertEqual(r['introduced_date'],'2023-08-10')
        self.assertEqual(r['assent_date'],'2023-12-28');self.assertIsNone(r['ls_passed_date'])
        self.assertIsNone(importer.date('31/02/2023'))

    def test_documents_only_allow_exact_official_hosts_and_paths(self):
        self.assertTrue(importer.safe_url('https://sansad.in/getFile/BillsTexts/example.pdf?source=legislation'))
        for url in ('http://sansad.in/getFile/a.pdf','https://sansad.in.evil.org/getFile/a.pdf',
                    'https://sansad.in:444/getFile/a.pdf','https://user@sansad.in/getFile/a.pdf',
                    'javascript:alert(1)','https://sansad.in/api/a'):
            self.assertFalse(importer.safe_url(url))

    def test_status_labels_merge_without_duplicate_bill(self):
        a=importer.normalize(raw());b=dict(a,status='Lapsed',source_statuses=['Lapsed'])
        self.assertTrue(importer.merge_status_variants(a,b))
        self.assertEqual(a['source_statuses'],['Lapsed','Pending'])
        self.assertEqual(a['status'],'Lapsed / Pending')

    def test_conflicting_dates_do_not_merge(self):
        a=importer.normalize(raw());b=dict(a,ls_passed_date='2023-08-11')
        self.assertFalse(importer.merge_status_variants(a,b));self.assertIsNone(a['ls_passed_date'])

    def test_distinct_introducers_and_bill_versions_keep_identity(self):
        a=importer.normalize(raw(billIntroducedBy='Member A'))
        b=importer.normalize(raw(billIntroducedBy='Member B'))
        self.assertNotEqual(a['id'],b['id'])
        b=importer.normalize(raw(billIntroducedBy='Member A',billPassedInRSFile='https://sansad.in/getFile/p.pdf'))
        self.assertEqual(a['id'],b['id'])

    def test_origin_and_passage_are_independent(self):
        r=importer.normalize(raw(billPassedInLSDate='2023-08-12'))
        self.assertTrue(store.matches(r,tab='passed',house='lok_sabha',origin='rajya_sabha'))
        self.assertFalse(store.matches(r,tab='passed',house='both'))
        self.assertFalse(store.matches(r,tab='passed',house='rajya_sabha'))

    def test_missing_passage_does_not_infer_pending(self):
        r=importer.normalize(raw());r['status']='Lapsed'
        self.assertFalse(store.matches(r,tab='pending'))

    def test_passed_is_not_automatically_an_act(self):
        r=importer.normalize(raw(billPassedInLSDate='2023-08-11',billPassedInRSDate='2023-08-12'))
        self.assertTrue(store.matches(r,tab='passed'));self.assertFalse(store.is_act(r))
        r['act_number']='42';self.assertTrue(store.is_act(r));self.assertIsNone(r['assent_date'])

    def test_filters_counts_and_pagination(self):
        rows=[importer.normalize(raw(billIntroducedBy=str(i))) for i in range(3)]
        with patch.object(store,'catalogue',return_value={'records':rows}):
            r=store.list_bills(query='example',year=2023,origin='rajya_sabha',page=2,page_size=2)
            self.assertEqual(r['total'],3);self.assertEqual(len(r['records']),1);self.assertEqual(r['counts']['pending'],3)
            self.assertEqual(store.list_bills(query='unmatched')['total'],0)
            self.assertIsNotNone(store.details(rows[0]['id']));self.assertIsNone(store.details('unknown'))

    def test_snapshot_refreshes_after_file_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'catalogue.json'
            with patch.object(store,'path',return_value=p):
                self.assertEqual(store.catalogue()['records'],[])
                p.write_text(json.dumps({'manifest':{'records':1},'records':[{'id':'first'}]}))
                self.assertEqual(store.catalogue()['records'][0]['id'],'first')
                p.write_text(json.dumps({'manifest':{'records':1},'records':[{'id':'changed-version'}]}))
                self.assertEqual(store.catalogue()['records'][0]['id'],'changed-version')


if __name__=='__main__':unittest.main()
