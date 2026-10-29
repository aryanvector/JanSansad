import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lok_sabha_rag.core import record_people as p
from lok_sabha_rag.api.routes.record_people import decorate


def bill():
    return {'id':'B_test','title':'The Example Bill, 2023','introduced_date':'2023-12-18','introduced_by':None,'origin_house':'Lok Sabha','sources':['https://sansad.in/ls/legislation/bills']}

def debate():
    return {'question_id':'LS_D_test','date':'2023-12-18','subject':'Example Bill, 2023 (Introduced)','house':'lok_sabha','mp_names':['Pratima Mondal'],'source_url':'https://sansad.in/ls/debates/digitized','source_pdf_url':'https://elibrary.sansad.in/server/api/core/bitstreams/abc/content'}


class PeopleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        patcher=patch.object(p,'DATA_DIR',Path(self.temp.name));patcher.start();self.addCleanup(patcher.stop)

    def test_explicit_speaker_heading(self):
        turns=p.speaker_turns('SHRIMATI PRATIMA MONDAL (JAYNAGAR): I request a railway bridge.')
        self.assertEqual(turns[0]['name'],'Pratima Mondal')

    def test_wrapped_minister_name(self):
        text='THE MINISTER OF COMMUNICATIONS (SHRI ASHWINI\nVAISHNAW): Sir, I introduce* the Bill.'
        actor=p.introduction_actor(text);self.assertEqual(actor['name'],'Ashwini Vaishnaw');self.assertEqual(actor['role'],'Introduced the bill')

    def test_objector_is_not_presenter(self):
        text='SHRI RITESH PANDEY: I object to introduction of this bill.\nSHRI ASHWINI VAISHNAW: Sir, I introduce the Bill.'
        self.assertEqual(p.introduction_actor(text)['name'],'Ashwini Vaishnaw')

    def test_quoted_introduction_is_not_presenter(self):
        self.assertIsNone(p.introduction_actor('SHRI OTHER MEMBER: The minister said I introduce the Bill but I object.'))

    def test_signature_is_not_introduction(self):
        self.assertIsNone(p.introduction_actor('STATEMENT OF OBJECTS AND REASONS\nASHWINI VAISHNAW\nNEW DELHI'))

    def test_excerpt_does_not_attribute_chair_remarks_to_presenter(self):
        text='SHRI ASHWINI VAISHNAW: Sir, I introduce the Bill.\nमाननीय सभापति: Please return to your seats.'
        actor=p.introduction_actor(text)
        self.assertNotIn('Please return',actor['excerpt']);self.assertNotIn('सभापति',actor['excerpt'])

    def test_motion_and_actual_introduction_have_distinct_roles(self):
        text='THE MINISTER (SHRI ASHWINI VAISHNAW): Hon. Chairperson Sir, I rise to move for leave to introduce a Bill.'
        self.assertEqual(p.introduction_actor(text)['role'],'Moved the introduction motion')

    def test_honorific_and_unicode_identity_keys(self):
        self.assertEqual(p.name_key('Shrimati Pratima Mondal'),p.name_key('PRATIMA MONDAL'))
        self.assertNotEqual(p.name_key('राम कुमार'),p.name_key('रीम कुमार'))

    def test_participant_and_explicit_speaker_are_merged(self):
        r=debate()
        with patch.object(p.debate_fulltext,'get',return_value={'status':'extracted','text':'SHRIMATI PRATIMA MONDAL (JAYNAGAR): A request for a bridge.','record':r}):out=p.debate_people(r)
        self.assertEqual(len(out['people']),1);self.assertEqual(len(out['people'][0]['roles']),2)
        self.assertIn('Named speaker',out['people'][0]['roles'][1])

    def test_missing_transcript_keeps_only_catalogue_role(self):
        with patch.object(p.debate_fulltext,'get',return_value=None),patch.object(p.debate_store,'transcript',return_value={'status':'unavailable','text':'metadata'}):out=p.debate_people(debate())
        self.assertEqual(out['people'][0]['roles'],['Listed debate participant'])

    def test_catalogue_presenter_does_not_trigger_pdf_lookup(self):
        r=bill();r['introduced_by']='Shri Member Name'
        with patch.object(p,'introduction_candidates',side_effect=AssertionError('should use explicit metadata')):out=p.bill_people(r)
        self.assertEqual(out['attribution_method'],'official_catalogue')

    def test_similar_bill_and_wrong_year_not_matched(self):
        dbfile=Path(self.temp.name)/'debates.db'
        with sqlite3.connect(dbfile) as db:
            db.execute('CREATE TABLE records(date TEXT,record TEXT)')
            for i,title in enumerate(('The Example Bill, 2023 (Introduced)','The Example Amendment Bill, 2023 (Introduced)','The Example Bill, 2024 (Introduced)')):
                r={**debate(),'question_id':f'LS_D_{i}','subject':title};db.execute('INSERT INTO records VALUES(?,?)',(r['date'],json.dumps(r)))
        with patch.object(p.debate_store,'ls_path',return_value=dbfile):out=p.introduction_candidates(bill())
        self.assertEqual([r['question_id'] for r in out],['LS_D_0'])

    def test_missing_metadata_never_infers_current_minister(self):
        r={**bill(),'ministry':'FINANCE'}
        with patch.object(p,'introduction_candidates',return_value=[]):out=p.bill_people(r)
        self.assertEqual(out['people'],[]);self.assertEqual(out['attribution_method'],'unavailable')

    def test_adjacent_bill_introductions_are_isolated(self):
        text='Other Bill (Introduced)\nSHRI OTHER MEMBER: I introduce the Bill.\nExample Bill (Introduced)\nSHRI ACTUAL MEMBER: Sir, I introduce the Bill.\nNext Bill (Introduced)\nSHRI THIRD MEMBER: I introduce the Bill.'
        scoped=p.introduction_section(text,bill()['title'])
        self.assertNotIn('OTHER MEMBER',scoped);self.assertNotIn('THIRD MEMBER',scoped)
        self.assertEqual(p.introduction_actor(scoped)['name'],'Actual Member')

    def test_missing_bill_heading_is_not_used(self):
        self.assertEqual(p.introduction_section('Unrelated Bill\nSHRI OTHER MEMBER: I introduce the Bill.',bill()['title']),'')

    def test_verified_presenter_is_cached_and_metadata_changes_invalidate(self):
        r=bill();text='Example Bill (Introduced)\nSHRI ACTUAL MEMBER: Sir, I introduce the Bill.'
        with patch.object(p,'introduction_candidates',return_value=[debate()]),patch.object(p.debate_store,'transcript',return_value={'status':'extracted','text':text}):out=p.bill_people(r)
        self.assertEqual(out['people'][0]['name'],'Actual Member')
        with patch.object(p,'introduction_candidates',side_effect=AssertionError('cache should be used')):self.assertEqual(p.bill_people(r),out)
        changed={**r,'introduced_date':'2023-12-19'}
        with patch.object(p,'introduction_candidates',return_value=[]):self.assertEqual(p.bill_people(changed)['people'],[])

    def test_rs_participants_are_not_matched_to_ls_directory(self):
        data={'house':'rajya_sabha','people':[{'name':'Member Name','roles':['Listed debate participant'],'source_url':'https://sansad.in/rs/debates/officials','excerpt':None}]}
        with patch('lok_sabha_rag.api.routes.record_people.profiles.directory',side_effect=AssertionError('wrong House directory')), patch('lok_sabha_rag.api.routes.rs_profiles.directory',return_value=({},{})):out=decorate(data)
        self.assertFalse(out['people'][0]['profile']['matched'])


if __name__=='__main__':unittest.main()
