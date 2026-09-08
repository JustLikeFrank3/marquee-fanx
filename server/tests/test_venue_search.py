import asyncio
from datetime import date
from unittest.mock import AsyncMock
from server.data import EventSource
from server.models import Search

def test_empty_keyword_search_resolves_venue_preserving_filters():
    source=EventSource('live')
    source.request=AsyncMock(side_effect=[
        ({'events':[]},'first'),
        ({'venues':[{'id':518875,'name':'The Eastern - Atlanta','city':'Atlanta'},
                    {'id':2,'name':'Unrelated venue','city':'Atlanta'},
                    {'id':3,'name':'The Eastern','city':'Boston'}]},'lookup'),
        ({'events':[{'id':123}]},'venue-fetch')])
    args=Search(query='eastern',city='Atlanta',date_from=date(2026,9,7),date_to=date(2026,10,7),type='concert',limit=9)
    rows,fetched=asyncio.run(source.search(args))
    assert rows==[{'id':123}] and fetched=='venue-fetch'
    params=source.request.call_args_list[-1].args[1]
    assert params=={'venue.city':'Atlanta','datetime_local.gte':'2026-09-07','datetime_local.lt':'2026-10-08',
                    'per_page':100,'sort':'datetime_local.asc','taxonomies.name':'concert','venue.id':'518875'}

def test_successful_event_search_does_not_trigger_venue_lookup():
    source=EventSource('live');source.request=AsyncMock(return_value=({'events':[{'id':1}]},'time'))
    args=Search(query='artist',date_from=date(2026,9,7),date_to=date(2026,10,7))
    assert asyncio.run(source.search(args))[0]==[{'id':1}]
    assert source.request.call_count==1

def test_unrelated_venue_results_do_not_widen_search():
    source=EventSource('live');source.request=AsyncMock(side_effect=[({'events':[]},'time'),
       ({'venues':[{'id':1,'name':'Other venue','city':'Atlanta'}]},'venue')])
    args=Search(query='eastern',date_from=date(2026,9,7),date_to=date(2026,10,7))
    assert asyncio.run(source.search(args))[0]==[]
    assert source.request.call_count==2
