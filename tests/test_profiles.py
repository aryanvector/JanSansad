"""Identity and attribution safeguards; these tests make no network requests."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from lok_sabha_rag.api.routes import profiles as p
from lok_sabha_rag.api.routes.question_text import QuestionTextRequest

class ProfilesTests(unittest.TestCase):
    def test_answer_heading_not_question(self):
        text = 'Will the Minister (SHRI WRONG NAME) reply?\n## A N S W E R\nTHE MINISTER OF POWER\n(SHRI R.K. SINGH)\n(a) Facts.'
        result = p.answerer(text)
        self.assertEqual(result['name'], 'Shri R.K. Singh')
        self.assertEqual(result['role_in_record'], 'THE MINISTER OF POWER')

    def test_no_answerer_without_heading(self):
        self.assertIsNone(p.answerer('Question mentions (SHRI SOME NAME).'))

    def test_answer_heading_without_the_and_with_colon(self):
        text='## ANSWER:\n\n## MINISTER OF STATE IN THE MINISTRY OF EDUCATION (SHRI JAYANT CHAUDHARY)\n\n- (a) Facts.'
        self.assertEqual(p.answerer(text)['name'], 'Shri Jayant Chaudhary')

    def test_body_mention_is_not_assigned_as_answerer(self):
        text='## ANSWER\n(a) Details were discussed.\nTHE MINISTER OF EDUCATION (SHRI SOME NAME) was mentioned.'
        self.assertIsNone(p.answerer(text))

    def test_ambiguous_identity_is_not_assigned(self):
        self.assertFalse(p.person('R K Singh', {}, {p.normalise('R K Singh'):{1,2}})['matched'])

    def test_exact_alias_order_and_titles(self):
        self.assertEqual(p.normalise('Singh, Shri Raj Kumar'), p.normalise('Raj Kumar Singh'))
        self.assertEqual(p.normalise('Shri R.K. Singh'), p.normalise('R K Singh'))
        self.assertNotEqual(p.normalise('R K Singh'), p.normalise('K R Singh'))

    def test_term_disambiguation_and_middle_name_omission(self):
        def member(name, terms):
            return dict(mpFirstLastName=name, lsExpr=terms, imageUrl=None, partyFname='', stateName='', constName='', retrieved_at='2026-10-08')
        members={1:member('Raj Kumar Singh','16,17'),2:member('Rama Kishore Singh','16'),3:member('Shripad Yesso Naik','17,18')}
        aliases={p.normalise('R K Singh'):{1,2}}
        self.assertFalse(p.person('R K Singh',members,aliases,16)['matched'])
        self.assertEqual(p.person('R K Singh',members,aliases,17)['id'],1)
        self.assertEqual(p.person('Shripad Naik',members,aliases,18)['id'],3)

    def test_multiple_questioners_and_bad_literal(self):
        self.assertEqual(p.names("['A', 'B']"), ['A','B'])
        self.assertEqual(p.names('A; B'), ['A','B'])

    def test_photo_host_is_restricted(self):
        self.assertIsNone(p.safe_photo('https://sansad.in.evil.test/photo'))
        self.assertIsNone(p.safe_photo('javascript:alert(1)'))
        self.assertEqual(p.safe_photo('https://sansad.in/getFile/x'), 'https://sansad.in/getFile/x')

    def test_context_reports_missing_answerer_without_guessing(self):
        chunk=SimpleNamespace(text='An answer without an identifiable minister heading.',asked_by="['A']",ministry='POWER',pdf_url='https://sansad.in/getFile/example')
        with patch.object(p._retriever,'_fetch_leading_chunks',return_value=[chunk]), patch.object(p,'directory',return_value=({},{})):
            result=p.context(QuestionTextRequest(question_id='17_7_1_UNSTARRED'))
        self.assertIsNone(result['answered_by'])
        self.assertIn('could not be identified',result['answerer_note'])

    def test_html_in_official_text_is_plain_text(self):
        self.assertEqual(p.clean('<body>Elected to 17<sup>th</sup> Lok Sabha</body>'), 'Elected to 17 th Lok Sabha')

    def test_context_uses_stored_record_date_when_pdf_heading_has_dash(self):
        chunk=SimpleNamespace(text='ANSWERED ON - 16/03/2026\n## ANSWER\nNo heading.',asked_by="['A']",ministry='EDUCATION',pdf_url=None,date='2026-03-16')
        with patch.object(p._retriever,'_fetch_leading_chunks',return_value=[chunk]), patch.object(p,'directory',return_value=({},{})):
            result=p.context(QuestionTextRequest(question_id='18_7_3880_UNSTARRED'))
        self.assertEqual(result['record_date'],'2026-03-16')

    def test_answering_minister_can_have_verified_rs_profile_for_ls_question(self):
        chunk=SimpleNamespace(text='## ANSWER\nMINISTER OF EDUCATION (SHRI EXAMPLE NAME)\n(a) Facts.',asked_by='[]',ministry='EDUCATION',pdf_url=None,date='2026-03-16')
        with patch.object(p._retriever,'_fetch_leading_chunks',return_value=[chunk]), \
             patch.object(p,'directory',return_value=({},{})), \
             patch('lok_sabha_rag.api.routes.rs_profiles.person',return_value={'name':'Example Name','matched':True,'id':123,'profile_house':'rajya_sabha'}):
            result=p.context(QuestionTextRequest(question_id='18_7_3880_UNSTARRED'))
        self.assertEqual(result['answered_by']['profile_house'],'rajya_sabha')
        self.assertIn('MINISTER OF EDUCATION',result['answered_by']['role_in_record'])

if __name__=='__main__':
    unittest.main()
