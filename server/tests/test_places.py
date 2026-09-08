import asyncio
from unittest.mock import patch,AsyncMock
import httpx
import pytest
from server.places import PlacesSource,coordinates,distance
from server.models import Nearby
from server.data import DataError

RAW={'id':1,'title':'Concert','venue':{'name':'Venue','city':'Atlanta','location':{'lat':33.75,'lon':-84.35}}}

def test_coordinates_fail_closed():
    assert coordinates(None) is None
    assert coordinates({'lat':float('nan'),'lon':1}) is None
    assert coordinates({'lat':91,'lon':1}) is None
    assert distance(33.75,-84.35,33.75,-84.35)==0

def test_sample_venue_never_queries_real_places():
    result=asyncio.run(PlacesSource().search(RAW,'sample',Nearby(event_id=1)))
    assert result['status']=='unavailable' and result['places']==[]
    assert result['policy_status']=='unconfirmed'

def test_radius_and_category_filter_and_unknown_facts(monkeypatch):
    monkeypatch.setenv('AZURE_MAPS_KEY','test-secret')
    response=httpx.Response(200,json={'results':[
        {'id':'near','poi':{'name':'Nearby'},'position':{'lat':33.7501,'lon':-84.35}},
        {'id':'far','poi':{'name':'Far away'},'position':{'lat':34.75,'lon':-84.35}},
        {'id':'bad','poi':{'name':'Bad'},'position':{'lat':999,'lon':-84.35}}]},request=httpx.Request('GET','https://atlas.microsoft.com'))
    with patch('httpx.AsyncClient.get',new=AsyncMock(return_value=response)) as get:
        result=asyncio.run(PlacesSource().search(RAW,'live',Nearby(event_id=1,category='bar')))
        assert get.call_args.kwargs['params']['categorySet']=='9379004,9379006,9379007'
    assert len(result['places'])==1
    p=result['places'][0]
    assert p['hours'] is None and p['price'] is None and p['availability'] is None
    assert 'test-secret' not in str(result)
    assert 'walking' in p['directions_url']

def test_missing_configuration_and_provider_error(monkeypatch):
    monkeypatch.delenv('AZURE_MAPS_KEY',raising=False)
    with pytest.raises(DataError): asyncio.run(PlacesSource().search(RAW,'live',Nearby(event_id=1)))
    monkeypatch.setenv('AZURE_MAPS_KEY','secret')
    with patch('httpx.AsyncClient.get',new=AsyncMock(side_effect=httpx.ConnectError('secret'))):
        with pytest.raises(DataError) as exc: asyncio.run(PlacesSource().search(RAW,'live',Nearby(event_id=1)))
    assert 'secret' not in str(exc.value)
