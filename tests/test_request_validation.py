from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from lok_sabha_rag.api.schemas import SearchRequest, SynthesizeRequest
from lok_sabha_rag.api.routes import question_text, profiles


@pytest.mark.parametrize('model', [SearchRequest, SynthesizeRequest])
@pytest.mark.parametrize('query', [' ', '\n\t', ''])
def test_blank_query_rejected_before_search_or_generation(model, query):
    with pytest.raises(ValidationError):
        model(query=query)


def test_normal_query_trimmed_without_changing_content():
    assert SearchRequest(query='  railway safety\n').query == 'railway safety'
    assert SynthesizeRequest(query=' Kavach 4.0? ').query == 'Kavach 4.0?'


@pytest.mark.parametrize('body', [{}, {'question_id':'  '}, {'lok_no':18},
    {'lok_no':18,'session_no':7,'ques_no':1},
    {'lok_no':18,'session_no':7,'ques_no':1,'type':'unknown'},
    {'lok_no':18,'session_no':0,'ques_no':1,'type':'Starred'}])
def test_incomplete_or_ambiguous_source_request_returns_422_not_500(body):
    app = FastAPI()
    app.include_router(question_text.router)
    app.include_router(profiles.router)
    with patch.object(question_text._retriever, '_fetch_leading_chunks') as fetch:
        client = TestClient(app)
        assert client.post('/question-text',json=body).status_code == 422
        assert client.post('/parliamentary-context',json=body).status_code == 422
    fetch.assert_not_called()


def test_legacy_identity_and_question_type_remain_supported():
    req=question_text.QuestionTextRequest(lok_no=18,session_no=7,ques_no=1,type=' Unstarred ')
    assert req.type == 'UNSTARRED'
    assert question_text.QuestionTextRequest(question_id=' 18_7_1_UNSTARRED ').question_id == '18_7_1_UNSTARRED'
