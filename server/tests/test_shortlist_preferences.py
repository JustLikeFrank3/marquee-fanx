import asyncio
from unittest.mock import AsyncMock
from server.models import Plan
from server.data import EventSource,now_iso
from server.tools import ToolService
from server.evidence import EvidenceStore

def args(**kw): return Plan(date_from='2026-10-01',date_to='2026-10-31',**kw)

def test_planning_pages_beyond_first_nine_and_preserves_dates():
    source=EventSource('live')
    source.request=AsyncMock(side_effect=[({'events':[{'id':i} for i in range(100)]},'stamp'),({'events':[{'id':100}]},'stamp2')])
    rows,_=asyncio.run(source.search(args()))
    assert len(rows)==101
    assert source.request.call_args_list[0].args[1]['per_page']==100
    assert source.request.call_args_list[1].args[1]['page']==2
    assert source.request.call_args_list[1].args[1]['datetime_local.lt']=='2026-11-01'

def test_october_favorites_beat_earlier_events():
    rows=[]
    for i,(title,day) in enumerate([('Other early show',1),('Another early show',2),('ATLiens',3),('Streetlight Manifesto',4),('Rodrigo Y Gabriela',13),('DJ Shadow',24)]):
        rows.append({'id':i+1,'title':title,'datetime_local':f'2026-10-{day:02}T20:00:00','venue':{'name':'The Eastern','city':'Atlanta'},'performers':[{'name':title}],'stats':{}})
    source=EventSource('live');source.search=AsyncMock(return_value=(rows,now_iso()))
    store=EvidenceStore();service=ToolService(source,store)
    result=asyncio.run(service.call('plan_night',args(favorite_artists=['Streetlight Manifesto','DJ Shadow','Rodrigo y Gabriela']).model_dump(mode='json'),store.create()))
    assert [e['title'] for e in result['events']]==['Streetlight Manifesto','Rodrigo Y Gabriela','DJ Shadow']
    assert all(e['why'].startswith('Matches your favorite artist:') for e in result['events'])
    assert '6 candidates' in result['scope']
    result=asyncio.run(service.call('plan_night',args(weekdays=[5],shortlist_size=5).model_dump(mode='json'),store.create()))
    assert [e['title'] for e in result['events']]==['ATLiens','DJ Shadow']

def test_unmatched_venue_does_not_fall_back_to_city():
    source=EventSource('live');source.request=AsyncMock(return_value=({'venues':[]},now_iso()))
    assert asyncio.run(source.search(args(venue_query='Not a venue')))[0]==[]
    assert source.request.call_count==1
