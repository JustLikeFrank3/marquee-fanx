import asyncio
from datetime import date,timedelta
from unittest.mock import AsyncMock
from server.data import EventSource,sample_records,now_iso
from server.evidence import EvidenceStore
from server.tools import ToolService

def run(records,budget=None):
    source=EventSource('sample');source.search=AsyncMock(return_value=(records,now_iso()))
    store=EvidenceStore();service=ToolService(source,store)
    return asyncio.run(service.call('plan_night',{'date_from':str(date.today()),'date_to':str(date.today()+timedelta(days=30)),
                    'budget_usd':budget,'party_size':2},store.create()))

def test_discovery_does_not_require_prices():
    records=sample_records()
    for record in records:record['stats']={}
    result=run(records)
    assert len(result['events'])==3
    assert all(e['budget_status']=='not_requested' and e['lowest_price'] is None for e in result['events'])
    assert all(e['facts'] and e['why'] for e in result['events'])
    assert result['pricing_available'] is False

def test_budget_keeps_unknowns_but_never_calls_them_affordable():
    records=sample_records()
    result=run(records,60)
    assert all(e['lowest_price'] is None or e['lowest_price']*2<=60 for e in result['events'])
    unknown=[e for e in result['events'] if e['lowest_price'] is None]
    assert unknown and all(e['budget_status']=='unknown' for e in unknown)
    assert 'not confirmed within budget' in result['scope']

def test_budget_excludes_known_over_budget_and_keeps_pricing():
    result=run(sample_records()[:1],60)
    assert result['events']==[]
    result=run(sample_records()[:1],120)
    assert result['events'][0]['budget_status']=='within_estimate'
    assert any(f['field']=='estimated_cost' for f in result['events'][0]['facts'])

def test_tbd_dates_not_presented_as_plans():
    records=sample_records()[:1];records[0]['date_tbd']=True
    assert run(records)['events']==[]
