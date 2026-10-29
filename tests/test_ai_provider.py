"""Provider routing, Gemini payloads and safe failures, without real credentials."""
import io
import json
import os
import unittest
from unittest.mock import Mock,patch
from urllib.error import HTTPError
from lok_sabha_rag.core import ai_provider as ai
from lok_sabha_rag.core.synthesizer import Synthesizer
from lok_sabha_rag.core import bill_documents


class AITests(unittest.TestCase):
    def setUp(self):
        p=patch.dict(os.environ,{'AI_PROVIDER':'gemini','GEMINI_API_KEY':'fake-test-key-not-a-real-secret','GEMINI_MODEL':'gemini-flash-latest'},clear=True)
        p.start();self.addCleanup(p.stop)

    def response(self,data):
        response=Mock();response.read.return_value=json.dumps(data).encode()
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response;return opener

    def test_public_status_has_no_secret(self):
        status=ai.configuration();self.assertEqual(status['provider'],'gemini');self.assertTrue(status['configured'])
        self.assertNotIn(os.environ['GEMINI_API_KEY'],json.dumps(status));self.assertNotIn('api_key',json.dumps(status))

    def test_auto_prefers_gemini(self):
        os.environ['AI_PROVIDER']='auto';self.assertEqual(ai.configuration()['provider'],'gemini')
        del os.environ['GEMINI_API_KEY'];os.environ['OPENAI_API_KEY']='fake-openai';self.assertEqual(ai.configuration()['provider'],'openai')

    def test_key_is_header_not_url_and_sources_are_in_user_input(self):
        opener=self.response({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'Supported [Q1].'}]}}]})
        with patch.object(ai,'build_opener',return_value=opener):text=ai.generate('System rules','Question and public evidence')
        request=opener.open.call_args.args[0];body=json.loads(request.data)
        self.assertEqual(text,'Supported [Q1].');self.assertNotIn(os.environ['GEMINI_API_KEY'],request.full_url)
        self.assertIn('System rules',body['systemInstruction']['parts'][0]['text'])
        self.assertIn('public evidence',body['contents'][0]['parts'][0]['text'])

    def test_private_thought_parts_are_not_returned(self):
        opener=self.response({'candidates':[{'finishReason':'STOP','content':{'parts':[{'thought':True,'text':'hidden reasoning'},{'text':'Visible answer.'}]}}]})
        with patch.object(ai,'build_opener',return_value=opener):self.assertEqual(ai.generate('s','u'),'Visible answer.')

    def test_missing_and_incomplete_answers_are_not_shown(self):
        for data in ({'candidates':[]},{'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'Partial'}]}}]}):
            with patch.object(ai,'build_opener',return_value=self.response(data)):
                with self.assertRaises(ai.GenerationError):ai.generate('s','u')

    def test_upstream_credentials_are_never_echoed_in_errors(self):
        for status,code in ((403,'authentication_failed'),(429,'rate_limit'),(404,'model_unavailable')):
            error=HTTPError('https://example.invalid',status,'raw-secret-from-provider',{},io.BytesIO(b'{"error":{"message":"private-credential"}}'))
            opener=Mock();opener.open.side_effect=error
            with patch.object(ai,'build_opener',return_value=opener):
                with self.assertRaises(ai.GenerationError) as ctx:ai.generate('s','u')
            self.assertEqual(ctx.exception.code,code);self.assertNotIn('private-credential',str(ctx.exception));self.assertNotIn('raw-secret',str(ctx.exception))

    def test_invalid_model_is_not_a_url(self):
        os.environ['GEMINI_MODEL']='../other?key=bad'
        with self.assertRaises(ai.GenerationError):ai.generate('s','u')

    def test_no_key_gives_safe_configuration_error(self):
        del os.environ['GEMINI_API_KEY']
        with self.assertRaises(ai.GenerationError) as ctx:ai.generate('s','u')
        self.assertEqual(ctx.exception.code,'not_configured')

    def test_parliament_and_bill_share_provider(self):
        with patch.object(ai,'generate',return_value='Answer [Q1].') as gen:
            self.assertEqual(Synthesizer().generate('question','context'),'Answer [Q1].')
            self.assertIn('context',gen.call_args.args[1])
        with patch.object(ai,'generate',return_value='Bill answer [E1].') as gen:
            self.assertEqual(bill_documents.generate_answer('question','context'),'Bill answer [E1].')
            self.assertEqual(gen.call_args.kwargs['task'],'bill')

    def test_redirects_never_forward_key(self):
        with self.assertRaises(ai.GenerationError):ai.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.test')

    def test_grouped_citations_become_individual_links(self):
        self.assertEqual(ai.normalize_citation_groups('Evidence [E1, E2].','E'),'Evidence [E1] [E2].')
        self.assertEqual(ai.normalize_citation_groups('Source [Q1 and Q3].','Q'),'Source [Q1] [Q3].')
        self.assertEqual(ai.normalize_citation_groups('[E1, E999]','E'),'[E1] [E999]')


if __name__=='__main__':unittest.main()
