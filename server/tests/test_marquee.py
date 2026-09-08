import asyncio
import copy
import time
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from server.data import EventSource, normalize, now_iso, sample_records, safe_url
from server.evidence import EvidenceStore, EvidenceError
from server.gate import statements, verify
from server.models import Search, Compare
from server.tools import ToolService, definitions

@pytest.fixture
def evidence():
    return [{'event':normalize(r,now_iso(),'sample'),'party_size':2} for r in sample_records()]

def test_canonical_statements(evidence):
    for item in evidence:
        result=verify('\n'.join(f['claim'] for f in statements(item['event'],2)),[item])
        assert result['verdict']=='PASS'

@pytest.mark.parametrize('line',[
    '[Event 1] Lowest listing statistic: $48.00.',
    '[Event 1] Lowest listing statistic: $52.50.',
    '[Event 1] Lowest listing statistic: $38.00.',
    '[Event 2] Lowest listing statistic: $52.00.',
    '[Event 1] Estimated total for 2: $103.99 (lowest listing statistic × party size; not a ticket offer).',
    '[Event 1] Estimated total for 3: $156.00 (lowest listing statistic × party size; not a ticket offer).',
    '[Event 1] Venue: The Signal Room, Boston, MA.',
    '[Event 1] Venue: Marquee Stadium, Atlanta, GA.',
    '[Event 999] Lowest listing statistic: $52.00.',
    '[Event 1] Tickets in section 112 cost $52.',
    '[Event 1] Row F has tickets.',
    '[Event 1] Seat 4 is available.',
    '[Event 1] Great views and no fees.',
    '[Event 1] Listing count: 113.',
    '[Event 1] Local date: 2000-09-12; local time: 19:30.',
    '[Event 1] Local date: 2026-09-12; local time: 19:31.',
    '[Event 1] Lowest listing statistic: $52.00. Seats guaranteed.',
    'NOT [Event 1] Lowest listing statistic: $52.00.',
    '$52 at The Signal Room',
    'Tickets are free.',
    '   ',
    '[Event 1] Event: An invented performance.',
])
def test_planted_false_claims_fail(line,evidence):
    assert verify(line,evidence)['verdict']=='FAIL'

def test_right_price_wrong_year(evidence):
    e=evidence[0]['event']
    line=statements(e,2)[2]['claim'].replace(e['date'][:4],str(int(e['date'][:4])+1))
    assert verify(line,evidence)['verdict']=='FAIL'

def test_supported_and_extra_prose_fail(evidence):
    line=statements(evidence[0]['event'],2)[0]['claim']
    result=verify(line+'\nThe view is unobstructed.',evidence)
    assert result['verdict']=='FAIL' and len(result['facts'])==1

def test_normalize_unknowns():
    raw=sample_records()[4]
    e=normalize(raw,now_iso(),'sample')
    assert e['time'] is None and e['lowest_price'] is None and e['listing_count']==0
    raw['date_tbd']=True
    assert normalize(raw,now_iso(),'sample')['date'] is None
    raw['datetime_local']='invalid'
    raw['stats']={'lowest_price':-2,'average_price':float('inf'),'highest_price':True,'listing_count':-1}
    e=normalize(raw,now_iso(),'sample')
    assert e['date'] is None and all(e[k] is None for k in ('lowest_price','average_price','highest_price','listing_count'))

def test_url_safety():
    assert safe_url('https://seatgeek.com/event')
    assert not safe_url('javascript:alert(1)')
    assert not safe_url('https://seatgeek.com.evil.test/')
    assert not safe_url('https://user:password@seatgeek.com')
    assert safe_url('https://chairnerd.global.ssl.fastly.net/a.jpg',True)

def test_session_isolation_expiry(evidence):
    store=EvidenceStore();a,b=store.create(),store.create()
    e=evidence[0]['event'];handle=store.add(a,e,{},2)
    assert store.get(a,[handle])[0]['event']['event_id']==1
    with pytest.raises(EvidenceError): store.get(b,[handle])
    store.sessions[a]['items'][handle]['expires']=0
    with pytest.raises(EvidenceError): store.get(a,[handle])
    store.sessions[b]['expires']=0
    with pytest.raises(EvidenceError): store.session(b)

def test_models():
    with pytest.raises(ValueError): Search(date_from=date.today(),date_to=date.today()-timedelta(days=1))
    with pytest.raises(ValueError): Compare(event_ids=[1,1])
    with pytest.raises(ValueError): Compare(event_ids=[-1,2])
    assert len(definitions())==6
    assert all(t['inputSchema']['additionalProperties'] is False for t in definitions())

def test_sample_search_and_budget():
    service=ToolService(EventSource('sample'),EvidenceStore());token=service.store.create()
    args={'city':'Atlanta','date_from':str(date.today()),'date_to':str(date.today()+timedelta(days=30))}
    result=asyncio.run(service.call('plan_night',{**args,'party_size':2,'budget_usd':60},token))
    assert result['events'] and all(e['lowest_price'] is None or e['lowest_price']*2<=60 for e in result['events'])
    assert asyncio.run(service.call('verify_plan',{'text':result['statements'],'evidence_ids':result['evidence_ids']},token))['verdict']=='PASS'
    assert not asyncio.run(service.call('search_events',{**args,'city':'Nowhere'},token))['events']

@pytest.fixture
def client(monkeypatch):
    import server.app as module
    monkeypatch.setattr(module,'service',ToolService(EventSource('sample'),EvidenceStore()))
    monkeypatch.setattr(module,'store',module.service.store)
    module.buckets.clear()
    return TestClient(module.app,base_url='http://localhost:8000')

def test_api_and_mcp_parity(client):
    token=client.post('/api/session').json()['session_id']
    headers={'X-Marquee-Session':token}
    args={'event_id':1}
    api=client.post('/api/event_details',json=args,headers=headers).json()
    rpc=client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'event_details','arguments':args}},headers=headers).json()
    import json
    event=json.loads(rpc['result']['content'][0]['text'])['events'][0]
    assert api['events'][0]['title']==event['title']
    schemas=client.post('/mcp',json={'jsonrpc':'2.0','id':2,'method':'tools/list'}).json()
    assert schemas['result']['tools']==definitions()
    assert client.post('/mcp',json={'jsonrpc':'2.0','id':3,'method':'initialize'}).json()['result']['protocolVersion']=='2025-03-26'
    assert client.get('/mcp').status_code==405
    assert client.post('/mcp',json={'jsonrpc':'2.0','method':'notifications/initialized'}).status_code==202

def test_origin_and_malformed_inputs(client):
    assert client.post('/api/session',headers={'Origin':'https://evil.test'}).status_code==403
    assert client.post('/mcp',content='bad').status_code==400
    assert client.post('/mcp',json=[]).status_code==400
    assert client.post('/api/search_events',content='a'*25000).status_code==413
    assert client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'nope'}).json()['error']['code']==-32601
    assert client.post('/api/event_details',json={'event_id':1}).status_code==401

def test_forwarded_ip_rate_buckets_only_when_opted_in(client,monkeypatch):
    import server.app as module
    monkeypatch.setenv('TRUST_FORWARDED_FOR','1')
    for _ in range(120):
        assert client.get('/api/health',headers={'X-Forwarded-For':'9.9.9.9, 1.1.1.1'}).status_code==200
    assert '1.1.1.1' in module.buckets
    assert client.get('/api/health',headers={'X-Forwarded-For':'9.9.9.9, 1.1.1.1'}).status_code==429
    # A different real client (last hop) has its own budget; spoofable early entries are ignored.
    assert client.get('/api/health',headers={'X-Forwarded-For':'9.9.9.9, 2.2.2.2'}).status_code==200
    monkeypatch.delenv('TRUST_FORWARDED_FOR')
    module.buckets.clear()
    client.get('/api/health',headers={'X-Forwarded-For':'3.3.3.3'})
    assert '3.3.3.3' not in module.buckets

def test_expired_source_snapshot_cannot_pass(evidence):
    store=EvidenceStore();token=store.create();e=copy.deepcopy(evidence[0]['event']);e['fetched_at']='2000-01-01T00:00:00+00:00'
    h=store.add(token,e,{},2)
    with pytest.raises(EvidenceError):store.get(token,[h])
