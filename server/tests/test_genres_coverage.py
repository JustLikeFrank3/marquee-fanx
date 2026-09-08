import asyncio
from unittest.mock import AsyncMock
from server.data import EventSource, SearchRecords, now_iso
from server.evidence import EvidenceStore
from server.tools import ToolService
from server.models import Plan

def event(i, day, genre=None):
    return {'id':i,'title':f'Artist {i}','datetime_local':f'2026-09-{day}T20:00:00',
            'venue':{'name':'Venue','city':'Atlanta'},'performers':[{'name':f'Artist {i}',
            'genres':[{'name':genre,'slug':genre.lower().replace(' ','-')}] if genre else []}]}

def search(rows, **args):
    source=EventSource('live'); source.search=AsyncMock(return_value=(SearchRecords(rows,len(rows)),now_iso()))
    store=EvidenceStore();service=ToolService(source,store);token=store.create()
    result=asyncio.run(service.call('search_events',{'date_from':'2026-09-11','date_to':'2026-09-13',**args},token))
    return result,source,service,token

def test_genre_query_is_not_sent_to_name_search_and_is_verified():
    result,source,service,token=search([event(1,'11','Punk'),event(2,'12','Rock'),event(3,'13')],query='punk rock')
    assert source.search.call_args.args[0].query==''
    assert [e['event_id'] for e in result['events']]==[1]
    assert result['genre_coverage']['untagged_candidates']==1
    report=asyncio.run(service.call('verify_plan',{'text':result['statements'],'evidence_ids':result['evidence_ids']},token))
    assert report['verdict']=='PASS'
    assert any(f['field']=='genre' for f in report['facts'])

def test_or_genres_do_not_guess_untagged_or_broaden_subgenres():
    result,*_=search([event(1,'11','Indie Rock'),event(2,'12','Jazz'),event(3,'13','Rock'),event(4,'13')],genres=['indie rock','jazz'])
    assert [e['event_id'] for e in result['events']]==[1,2]
    result,*_=search([event(3,'13','Rock')],genres=['punk rock'])
    assert not result['events']
    assert 'Not exhaustive' in result['scope']

def test_weekend_balances_dates_not_first_friday_only():
    result,*_=search([event(i,'11') for i in range(20)]+[event(30,'12'),event(31,'13')],limit=9)
    assert result['coverage']['returned_dates']==['2026-09-11','2026-09-12','2026-09-13']
    assert result['coverage']['catalog_total']==22
    assert result['coverage']['exhaustive'] is False

def test_favorite_found_beyond_broad_candidate_cap():
    source=EventSource('live')
    source.request=AsyncMock(side_effect=[({'events':[event(i,'11') for i in range(n,n+100)],'meta':{'total':400}},now_iso()) for n in (0,100,200)]+[({'events':[event(999,'13')]},now_iso())])
    rows,_=asyncio.run(source.search(Plan(date_from='2026-09-11',date_to='2026-09-13',favorite_artists=['Artist 999'])))
    assert any(r['id']==999 for r in rows)
    assert source.request.call_args.args[1]['q']=='Artist 999'
    assert rows.truncated
