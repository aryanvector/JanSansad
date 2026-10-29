from types import SimpleNamespace as NS
import pytest
from lok_sabha_rag.core.relevance import relevant_items

def item(text, qid='one', **kw):
    return NS(text=text, subject=kw.get('subject', ''), asked_by=kw.get('asked_by', ''),
              ministry='', question_id=qid, house='lok_sabha')

@pytest.mark.parametrize('query', ['Aryan', 'my name is Aryan', 'cuss', 'fuck', 'asdfghjkl', '!!!', 'what is this', 'what is asdfghjkl in India'])
def test_unrelated_neighbours_are_not_evidence(query):
    assert relevant_items(query, [item('Railway safety and coach production')]) == []

def test_exact_name_is_allowed_when_actually_supported():
    record = item('Scholarship eligibility for Aryan communities')
    assert relevant_items('Aryan', [record]) == [record]

def test_topics_and_common_paraphrases():
    record = item('Railways employment and safety: Kavach deployment')
    for query in ['What is Kavach?', 'railway development', 'jobs in railways']:
        assert relevant_items(query, [record]) == [record]

def test_unrelated_records_removed_and_complementary_chunks_retained():
    a,b,c=item('Kavach deployment'),item('Table: 200 kilometres'),item('Hospital beds','other')
    assert relevant_items('Kavach', [a,b,c]) == [a,b]

def test_word_boundaries_no_substring_match():
    assert relevant_items('Aryan', [item('Parliamentary annual summary')]) == []

def test_metadata_person_search():
    record=item('Budget allocation', asked_by='Example Person')
    assert relevant_items('Example Person', [record]) == [record]

def test_search_endpoint_rejects_neighbours(monkeypatch):
    from fastapi import HTTPException
    from lok_sabha_rag.api.routes import search
    from lok_sabha_rag.api.schemas import SearchRequest
    monkeypatch.setattr(search.retriever, 'search', lambda **kw: [item('Railway coaches')])
    with pytest.raises(HTTPException) as error:
        search.search(SearchRequest(query='Aryan'))
    assert error.value.status_code == 404

def test_synthesis_abstains_before_model_call(monkeypatch):
    from unittest.mock import Mock
    from fastapi import HTTPException
    from lok_sabha_rag.api.routes import synthesize
    from lok_sabha_rag.api.schemas import SynthesizeRequest
    monkeypatch.setattr(synthesize, 'retrieve_scoped', lambda *a, **k: None)
    monkeypatch.setattr(synthesize, 'retrieve_comparison', lambda *a, **k: ([item('Railway coaches')], []))
    model = Mock()
    monkeypatch.setattr(synthesize, 'generate_checked', model)
    with pytest.raises(HTTPException) as error:
        synthesize.synthesize(SynthesizeRequest(query='Aryan'))
    assert error.value.status_code == 404
    model.assert_not_called()
