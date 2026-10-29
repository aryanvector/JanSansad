from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lok_sabha_rag.core import minister_store as s
from lok_sabha_rag.api.routes import minister_directory


def row(identifier,name,government,level,portfolios,rank='Minister'):
    return {'id':identifier,'name':name,'jurisdiction_id':government,'jurisdiction':government,
        'level':level,'portfolios':portfolios,'portfolio_text':'; '.join(portfolios),'rank':rank,'order':0}


@pytest.fixture
def snapshot():
    data={'generated_at':'2026-10-25','jurisdictions':[
        {'id':'union','name':'Union','level':'union','record_count':2},
        {'id':'state-a','name':'State A','level':'state','record_count':1},
        {'id':'state-b','name':'State B','level':'state','record_count':0,'status':'not_imported'}],
        'records':[row('a','Minister One','union','union',['Railways'],'Cabinet Minister'),
                   row('b','Minister Two','union','union',['Railways'],'Minister of State'),
                   row('c','Minister One','state-a','state',['Health'])]}
    with patch.object(s,'catalogue',return_value=data):yield data


def test_ministry_query_returns_cabinet_and_junior_ministers(snapshot):
    assert {r['id'] for r in s.search('Ministry of Railways')['records']}=={'a','b'}


def test_name_search_preserves_different_governments(snapshot):
    assert {r['id'] for r in s.search('Minister One')['records']}=={'a','c'}


def test_level_and_location_filters_intersect(snapshot):
    assert s.search(level='state',jurisdiction='state-a')['total']==1
    assert s.search(level='union',jurisdiction='state-a')['total']==0


def test_missing_roster_is_not_vacancy(snapshot):
    result=s.search(jurisdiction='state-b')
    assert result['total']==0 and result['jurisdictions'][0]['status']=='not_imported'


def test_portfolio_filter_returns_all_listed_ranks(snapshot):
    assert s.search(portfolio='Railways')['total']==2
    assert s.search(portfolio='Railways',rank='Minister of State')['records'][0]['id']=='b'


def test_pagination_does_not_duplicate_or_omit(snapshot):
    pages=[s.search(page=p,page_size=1)['records'][0]['id'] for p in (1,2,3)]
    assert len(set(pages))==3


def test_unmatched_query_does_not_fabricate_answers(snapshot):
    assert s.search('No Such Person')['records']==[]


def test_literal_html_is_data_not_query_code(snapshot):
    assert s.search('<script>alert(1)</script>')['records']==[]


def test_api_validation_and_results(snapshot):
    app=FastAPI();app.include_router(minister_directory.router,prefix='/api');client=TestClient(app)
    assert client.get('/api/minister-directory',params={'query':'railways'}).json()['total']==2
    for params in ({'level':'invalid'},{'page':0},{'page_size':1000},{'query':'x'*201}):
        assert client.get('/api/minister-directory',params=params).status_code==422


def test_state_member_never_assumed_to_be_parliamentarian(snapshot):
    assert minister_directory.profile('c')['matched'] is False


def test_shipped_snapshot_has_all_jurisdictions_and_consistent_counts():
    data=s.catalogue()
    assert len(data['jurisdictions'])==37
    assert sum(x['level']=='state' for x in data['jurisdictions'])==28
    assert sum(x['level']=='ut' for x in data['jurisdictions'])==8
    assert len({r['id'] for r in data['records']})==len(data['records'])
    for scope in data['jurisdictions']:
        assert scope['record_count']==sum(r['jurisdiction_id']==scope['id'] for r in data['records'])


def test_source_records_exclude_contacts_and_missing_details_are_explicit():
    for row in s.catalogue()['records']:
        assert row['source_url'].startswith('https://') and row['fetched_at']
        assert not {'email','address','phone','mobile','contact'} & row.keys()
        assert isinstance(row['portfolios'],list)


def test_railways_current_source_roster_has_multiple_responsible_ministers():
    result=s.search('railways',jurisdiction='union')
    assert len(result['records'])>=2
    assert any('Ashwini' in r['name'] for r in result['records'])
    assert any(r['rank']=='Minister of State' for r in result['records'])


@pytest.mark.parametrize('query',['Vishnu Deo Sai','Vishnu Dev Sai','विष्णु देव साय','cm of chhattisgarh','who is cm of chhattisgarh'])
def test_verified_chhattisgarh_cm_and_name_variants(query):
    result=s.search(query)
    assert len(result['records'])==1
    assert result['records'][0]['name']=='Shri Vishnu Deo Sai'
    assert result['records'][0]['rank']=='Chief Minister'
    scope=s.search(jurisdiction='chhattisgarh')['jurisdictions'][0]
    assert scope['status']=='partial'


def test_cm_abbreviation_does_not_match_deputy_cm(snapshot):
    snapshot['records'].extend([row('cm','Leader','state-a','state',[],'Chief Minister'),row('deputy','Deputy Leader','state-a','state',[],'Deputy Chief Minister')])
    assert [r['id'] for r in s.search('cm',jurisdiction='state-a')['records']]==['cm']
