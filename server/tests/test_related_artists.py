import asyncio
from unittest.mock import AsyncMock
from server.lastfm import SimilarSource
from server.models import Plan
from server.data import EventSource, now_iso
from server.tools import ToolService
from server.evidence import EvidenceStore

def args(**kw): return Plan(date_from='2026-10-01',date_to='2026-10-31',**kw)

def rows():
    out=[]
    for i,(title,day) in enumerate([('Streetlight Manifesto',4),('Catch 22',10),('Random Openers',2),('Another Show',3)]):
        out.append({'id':i+1,'title':title,'datetime_local':f'2026-10-{day:02}T20:00:00',
                    'venue':{'name':'The Eastern','city':'Atlanta'},'performers':[{'name':title}],'stats':{}})
    return out

def service_with(similar,tags=None):
    source=EventSource('live');source.search=AsyncMock(return_value=(rows(),now_iso()))
    store=EvidenceStore();service=ToolService(source,store)
    service.lastfm.similar=AsyncMock(return_value=similar)
    service.lastfm.top_tags=AsyncMock(return_value=tags or {'status':'ok','source':'Last.fm artist.getSimilar','fetched_at':now_iso(),'seeds':{},'failed_seeds':[]})
    return service,store,source

def test_related_events_rank_between_favorites_and_alternatives():
    similar={'status':'ok','source':'Last.fm artist.getSimilar','fetched_at':now_iso(),
             'seeds':{'Streetlight Manifesto':[{'name':'Streetlight Manifesto','match':1.0},{'name':'Catch 22','match':0.92}]},
             'failed_seeds':[]}
    service,store,source=service_with(similar)
    result=asyncio.run(service.call('plan_night',args(favorite_artists=['Streetlight Manifesto'],include_related=True,shortlist_size=3).model_dump(mode='json'),store.create()))
    assert [e['title'] for e in result['events']]==['Streetlight Manifesto','Catch 22','Random Openers']
    assert result['events'][0]['why'].startswith('Matches your favorite artist: Streetlight Manifesto.')
    assert result['events'][1]['why'].startswith('Related discovery: Last.fm lists Catch 22 as similar to your favorite Streetlight Manifesto (match 0.92).')
    assert result['events'][2]['why'].startswith('Alternative:')
    assert 'Related-artist discovery via Last.fm searched 1 similar artists.' in result['scope']
    # The seed itself is excluded; only genuine discoveries are searched and attributed.
    assert result['related_discovery']['searched_artists']==[{'name':'Catch 22','similar_to':'Streetlight Manifesto','match':0.92}]
    assert source.search.call_args.args[1]==['Catch 22']

def test_unconfigured_lastfm_is_explicit_not_silent():
    similar={'status':'unconfigured','source':'Last.fm artist.getSimilar','fetched_at':now_iso(),
             'seeds':{},'failed_seeds':['Streetlight Manifesto'],'note':'Last.fm similarity is not configured on this server.'}
    service,store,source=service_with(similar)
    result=asyncio.run(service.call('plan_night',args(favorite_artists=['Streetlight Manifesto'],include_related=True).model_dump(mode='json'),store.create()))
    assert 'Last.fm similarity is not configured on this server.' in result['scope']
    assert result['related_discovery']['status']=='unconfigured'
    assert source.search.call_args.args[1]==[]
    assert not any('Related discovery' in e['why'] for e in result['events'])

def test_failed_lastfm_lookup_keeps_shortlist_and_says_so():
    similar={'status':'error','source':'Last.fm artist.getSimilar','fetched_at':now_iso(),
             'seeds':{},'failed_seeds':['Streetlight Manifesto']}
    service,store,_=service_with(similar)
    result=asyncio.run(service.call('plan_night',args(favorite_artists=['Streetlight Manifesto'],include_related=True).model_dump(mode='json'),store.create()))
    assert 'Last.fm similarity lookup failed' in result['scope']
    assert result['events']

def test_related_without_favorites_notes_requirement():
    service,store,_=service_with(None)
    result=asyncio.run(service.call('plan_night',args(include_related=True).model_dump(mode='json'),store.create()))
    assert 'Related-artist discovery needs favorite artists' in result['scope']
    assert result['related_discovery']['status']=='no_seeds'
    service.lastfm.similar.assert_not_called()

def empty_similar(seed='Elder'):
    return {'status':'ok','source':'Last.fm artist.getSimilar','fetched_at':now_iso(),'seeds':{seed:[]},'failed_seeds':[]}

def test_tag_affinity_outranks_bare_coarse_genre_match():
    # Elder's profile: doom metal beats a bare Rock tag; Air Supply-style picks drop out.
    tags={'status':'ok','source':'Last.fm artist.getSimilar','fetched_at':now_iso(),
          'seeds':{'Elder':[{'name':'Stoner Rock','count':100},{'name':'Doom Metal','count':80},{'name':'Rock','count':60}]},'failed_seeds':[]}
    catalog=[{'id':1,'title':'Soft Duo','datetime_local':'2026-10-02T20:00:00','venue':{'name':'Hall','city':'Atlanta'},
              'performers':[{'name':'Soft Duo','genres':[{'name':'Pop','slug':'pop'},{'name':'Rock','slug':'rock'}]}],'stats':{}},
             {'id':2,'title':'Heavy Riffs','datetime_local':'2026-10-02T21:00:00','venue':{'name':'Hall','city':'Atlanta'},
              'performers':[{'name':'Heavy Riffs','genres':[{'name':'Doom Metal','slug':'doom-metal'},{'name':'Rock','slug':'rock'}]}],'stats':{}},
             {'id':3,'title':'Elder','datetime_local':'2026-10-05T20:00:00','venue':{'name':'Hall','city':'Atlanta'},
              'performers':[{'name':'Elder','genres':[{'name':'Stoner Rock','slug':'stoner-rock'}]}],'stats':{}}]
    service,store,source=service_with(empty_similar(),tags)
    source.search=AsyncMock(return_value=(catalog,now_iso()))
    result=asyncio.run(service.call('plan_night',args(favorite_artists=['Elder'],include_related=True,shortlist_size=2).model_dump(mode='json'),store.create()))
    assert [e['title'] for e in result['events']]==['Elder','Heavy Riffs']
    assert 'overlap your favorites\u2019 Last.fm top tags: doom metal' in result['events'][1]['why']
    assert 'Alternatives ordered by source-tag overlap' in result['scope']

def test_excluded_event_is_replaced_not_argued_for():
    tags={'status':'ok','source':'Last.fm artist.getSimilar','fetched_at':now_iso(),
          'seeds':{'Elder':[{'name':'Stoner Rock','count':100}]},'failed_seeds':[]}
    service,store,_=service_with(empty_similar(),tags)
    base=args(favorite_artists=['Elder'],include_related=True,shortlist_size=2)
    first=asyncio.run(service.call('plan_night',base.model_dump(mode='json'),store.create()))
    rejected=first['events'][1]['event_id']
    redo=asyncio.run(service.call('plan_night',base.model_copy(update={'exclude_event_ids':[rejected]}).model_dump(mode='json'),store.create()))
    assert all(e['event_id']!=rejected for e in redo['events'])
    assert f'Excluded at your request: event {rejected}.' in redo['scope']

def test_adapter_unconfigured_without_key(monkeypatch):
    monkeypatch.delenv('LASTFM_API_KEY',raising=False)
    result=asyncio.run(SimilarSource().similar(['DJ Shadow']))
    assert result['status']=='unconfigured'
    assert result['failed_seeds']==['DJ Shadow']

def test_adapter_caches_successes_and_reports_failures(monkeypatch):
    monkeypatch.setenv('LASTFM_API_KEY','test-key')
    source=SimilarSource()
    calls=[]
    async def fetch(seed,limit):
        calls.append(seed)
        return [{'name':'UNKLE','match':0.85}] if seed=='DJ Shadow' else None
    source._fetch=fetch
    result=asyncio.run(source.similar(['DJ Shadow','Broken Artist']))
    assert result['status']=='partial'
    assert result['seeds']=={'DJ Shadow':[{'name':'UNKLE','match':0.85}]}
    assert result['failed_seeds']==['Broken Artist']
    again=asyncio.run(source.similar(['DJ Shadow']))
    assert again['status']=='ok'
    assert calls.count('DJ Shadow')==1

class FakeResponse:
    def __init__(self,payload): self.payload=payload; self.status_code=200
    def json(self): return self.payload
    def raise_for_status(self): pass

class FakeClient:
    def __init__(self,payload): self.payload=payload
    async def __aenter__(self): return self
    async def __aexit__(self,*a): return False
    async def get(self,url,params=None): return FakeResponse(self.payload)

def test_fetch_parses_and_bounds_lastfm_rows(monkeypatch):
    monkeypatch.setenv('LASTFM_API_KEY','test-key')
    payload={'similarartists':{'artist':[{'name':'UNKLE','match':'0.851234'},{'name':'  ','match':'1'},{'name':'RJD2','match':'bad'}]}}
    monkeypatch.setattr('server.lastfm.httpx.AsyncClient',lambda **kw: FakeClient(payload))
    assert asyncio.run(SimilarSource()._fetch('DJ Shadow',5))==[{'name':'UNKLE','match':0.851},{'name':'RJD2','match':None}]

def test_fetch_treats_unknown_artist_as_empty_not_failure(monkeypatch):
    monkeypatch.setenv('LASTFM_API_KEY','test-key')
    monkeypatch.setattr('server.lastfm.httpx.AsyncClient',lambda **kw: FakeClient({'error':6,'message':'not found'}))
    assert asyncio.run(SimilarSource()._fetch('zzzz-not-an-artist',5))==[]
