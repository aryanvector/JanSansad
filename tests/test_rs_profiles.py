"""House-specific identity and source-backed biography regression checks."""
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from lok_sabha_rag.api.routes import rs_profiles as r
from lok_sabha_rag.api.routes import record_people


@pytest.fixture
def members():
    item={'name':'Dr. Bhim Singh','party':'BJP','state':'Bihar','photo_url':'https://sansad.in/getFile/rsnew/member_site/photos/P2590.jpg?source=rajyasabha','retrieved_at':'2026-10-25'}
    with patch.object(r,'directory',return_value=({2590:item},{r.profiles.normalise('Bhim Singh'):{2590}})):
        yield item


def test_exact_honorific_match(members):
    p=r.person('BHIM SINGH')
    assert p['id']==2590 and p['profile_house']=='rajya_sabha'


def test_unknown_stays_unknown(members):
    assert not r.person('Unknown Member')['matched']


def test_ambiguous_identity_refused():
    with patch.object(r,'directory',return_value=({},{'bhimsingh':{1,2}})):
        assert not r.person('Bhim Singh')['matched']


@pytest.mark.parametrize('url',['http://sansad.in/getFile/rsnew/member_site/photos/P1.jpg','https://evil.test/getFile/rsnew/member_site/photos/P1.jpg','https://sansad.in@evil.test/x','https://sansad.in:444/getFile/rsnew/member_site/photos/P1.jpg','https://sansad.in/other/file.jpg'])
def test_unapproved_photo_refused(url):
    assert r.safe_photo(url) is None


def test_relative_official_photo():
    assert r.safe_photo('/getFile/rsnew/member_site/photos/P1.jpg').startswith('https://sansad.in/')


def test_biography_returns_only_profile_fields(members):
    bio={'time':1,'data':{'mpCode':2590,'name':'Bhim Singh','qualification':'PhD','imageUrl':members['photo_url'],'email':'unused','mobile':'unused','address':'unused'}}
    positions={'time':2,'data':[{'period':'2024 onwards','position':'Member, Rajya Sabha'}]}
    with patch.object(r.profiles,'cached_json',side_effect=[bio,positions]):
        p=r.biography(2590)
    assert p['education']=='PhD' and len(p['career'])==1
    assert not {'email','mobile','address'} & p.keys()


def test_wrong_biography_identity_refused(members):
    with patch.object(r.profiles,'cached_json',return_value={'time':1,'data':{'mpCode':2425}}):
        with pytest.raises(HTTPException):r.biography(2590)


def context(text):
    row=SimpleNamespace(asked_by=['Bhim Singh'],date='2025-02-13',ministry='RAILWAYS',pdf_url=None)
    return r.question_context([row],text)


def test_questioner_uses_rs_only(members):
    with patch.object(r.profiles,'directory',side_effect=AssertionError('wrong House')):
        out=context('Question: who is the minister?')
    assert out['asked_by'][0]['id']==2590 and out['answered_by'] is None


def test_answer_requires_explicit_heading(members):
    assert context('MINISTER OF RAILWAYS (SHRI BHIM SINGH) mentioned in question')['answered_by'] is None
    p=context('ANSWER\nMINISTER OF RAILWAYS (SHRI BHIM SINGH)\nThe answer')['answered_by']
    assert p['id']==2590 and p['profile_house']=='rajya_sabha'


def test_body_only_minister_reference_not_used_for_attribution(members):
    out=context('ANSWER\n(a) A discussion was held.\nMINISTER OF RAILWAYS (SHRI BHIM SINGH) participated.')
    assert out['answered_by'] is None


def test_explicit_answerer_may_be_ls_member(members):
    with patch.object(r.profiles,'directory',return_value=({},{})),patch.object(r.profiles,'person',return_value={'name':'E. Ahamed','matched':True,'id':22}):
        p=context('ANSWER\nMINISTER OF STATE IN RAILWAYS (SHRI E. AHAMED)\nResponse')['answered_by']
    assert p['id']==22 and p['profile_house']=='lok_sabha'


def test_rs_record_gets_rs_profile(members):
    data={'house':'rajya_sabha','people':[{'name':'BHIM SINGH','roles':['Listed debate participant'],'source_url':'https://sansad.in/rs/debates/officials'}]}
    with patch.object(r.profiles,'directory',side_effect=AssertionError('wrong House')):
        p=record_people.decorate(data)['people'][0]['profile']
    assert p['id']==2590 and p['profile_house']=='rajya_sabha'
