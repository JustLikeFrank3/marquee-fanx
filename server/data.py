"""Public Platform API adapter. Synthetic mode is explicit, never a failure fallback."""
import asyncio
import copy
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlparse
import httpx
from .genres import labels

class DataError(Exception):
    pass

def now_iso():
    return datetime.now(timezone.utc).isoformat()

class SearchRecords(list):
    def __init__(self, rows, total=None, truncated=False):
        super().__init__(rows)
        self.total = total
        self.truncated = truncated

def safe_url(value, images=False):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    host = parsed.hostname or ''
    allowed = ('seatgeek.com', 'seatgeekcdn.com', 'sgcdn.com', 'seatgeekimages.com')
    valid = any(host == d or host.endswith('.'+d) for d in allowed)
    valid = valid or (images and host == 'chairnerd.global.ssl.fastly.net')
    return value if parsed.scheme == 'https' and valid and not parsed.username else None

def normalize(raw, fetched_at, mode):
    stats, venue = raw.get('stats') or {}, raw.get('venue') or {}
    def money(key):
        value = stats.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            return None
        return float(value) if Decimal(str(value)).is_finite() else None
    start = raw.get('datetime_local') or ''
    date_tbd, time_tbd = bool(raw.get('date_tbd')), bool(raw.get('time_tbd'))
    try:
        dt = datetime.fromisoformat(start)
    except (ValueError, TypeError):
        dt = None
    performers = raw.get('performers') or []
    url = safe_url(raw.get('url'))
    listing_count = stats.get('listing_count')
    return {'event_id': int(raw['id']), 'title': raw.get('title') or 'Untitled event',
            'kind': raw.get('type', 'event'), 'date': dt.date().isoformat() if dt and not date_tbd else None,
            'time': dt.strftime('%H:%M') if dt and not time_tbd and not date_tbd else None,
            'date_tbd': date_tbd or not dt, 'time_tbd': time_tbd or not dt,
            'timezone': venue.get('timezone'), 'venue_name': venue.get('name', 'Venue unavailable'),
            'city': venue.get('city', ''), 'state': venue.get('state', ''),
            'lowest_price': money('lowest_price'), 'average_price': money('average_price'),
            'highest_price': money('highest_price'),
            'listing_count': listing_count if isinstance(listing_count, int) and not isinstance(listing_count, bool) and listing_count >= 0 else None,
            'url': url, 'artwork_url': next((safe_url(p.get('image'), True) for p in performers if safe_url(p.get('image'), True)), None),
            'genres': labels(raw),
            'performers': [p.get('name') for p in performers if p.get('name')],
            'fetched_at': fetched_at, 'mode': mode,
            'seat_preview': {'status': 'external-link' if url and mode == 'live' else 'unavailable',
                             'reason': 'Section imagery is not supplied by this API. Explore seating on SeatGeek; preview availability varies.'}}

def sample_records():
    today = date.today()
    saturday = today + timedelta(days=(5-today.weekday()) % 7)
    events = []
    rows = [('Midnight Frequencies','concert','The Signal Room',52,84,112),
            ('Atlanta City vs. Coastal FC','sports','Marquee Stadium',38,96,280),
            ('Sunday in Stereo','concert','The Foundry Stage',28,46,78),
            ('An Evening of Strings','theater','Crescent Hall',35,62,140),
            ('The Last Laugh','theater','Peachtree Theatre',None,None,0),
            ('After Hours Jazz','concert','Bluebird Room',22,58,65)]
    for i,(title,kind,venue,low,avg,count) in enumerate(rows):
        day = saturday + timedelta(days=1 if i == 2 else 0)
        events.append({'id': i+1, 'title': title, 'type': kind, 'datetime_local': f'{day}T{19+i%3:02}:30:00',
                       'time_tbd': i == 4, 'date_tbd': False, 'venue': {'name':venue,'city':'Atlanta','state':'GA','timezone':'America/New_York'},
                       'stats': {'lowest_price':low,'average_price':avg,'highest_price':None if low is None else low*4,'listing_count':count},
                       'performers': [], 'url': None})
    return events

class EventSource:
    def __init__(self, mode=None):
        self.mode = mode or os.getenv('MARQUEE_DATA_MODE','sample')
        if self.mode not in ('sample','live'):
            raise RuntimeError('MARQUEE_DATA_MODE must be sample or live')
        self.cache = {}
        self.lock = asyncio.Lock()

    async def request(self, path, params):
        key = (path, tuple(sorted(params.items())))
        async with self.lock:
            now = time.monotonic()
            self.cache = {k:v for k,v in self.cache.items() if v[0] > now}
            if key in self.cache:
                return copy.deepcopy(self.cache[key][1])
            client_id = os.getenv('SEATGEEK_CLIENT_ID','')
            if not client_id:
                raise DataError('Live mode needs a SeatGeek client ID on the server.')
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                    for attempt in range(3):
                        response = await client.get('https://api.seatgeek.com/2/'+path, params=params,
                                                    auth=(client_id, os.getenv('SEATGEEK_CLIENT_SECRET','')))
                        if response.status_code == 429 or response.status_code >= 500:
                            if attempt < 2:
                                await asyncio.sleep(0.5 * (attempt+1))
                                continue
                        response.raise_for_status()
                        payload = (response.json(), now_iso())
                        if len(self.cache) >= 100:
                            self.cache.pop(next(iter(self.cache)))
                        self.cache[key] = (time.monotonic()+600, payload)
                        return copy.deepcopy(payload)
            except (httpx.HTTPError, ValueError):
                raise DataError('SeatGeek event data is unavailable. Check API access or try again later.') from None

    async def search(self, args, related_artists=()):
        planning = hasattr(args,'shortlist_size')
        if self.mode == 'sample':
            records = sample_records()
            records = [r for r in records if r['venue']['city'].casefold() == args.city.casefold()
                       and args.date_from.isoformat() <= r['datetime_local'][:10] <= args.date_to.isoformat()
                       and (args.type == 'any' or r['type'] == args.type)
                       and (not args.query or args.query.casefold() in (r['title']+' '+r['venue']['name']).casefold())]
            if planning and args.venue_query:
                records=[r for r in records if args.venue_query.casefold() in r['venue']['name'].casefold()]
            return SearchRecords(records[:300],len(records),len(records)>300), now_iso()
        params = {'venue.city':args.city,'datetime_local.gte':str(args.date_from),
                  'datetime_local.lt':str(args.date_to+timedelta(days=1)), 'per_page':100,'sort':'datetime_local.asc'}
        if planning and args.venue_query.strip():
            venues,_=await self.request('venues',{'q':args.venue_query.strip(),'city':args.city,'per_page':10})
            terms=re.findall(r'\w+',args.venue_query.casefold())
            matches=[v for v in venues.get('venues',[]) if (v.get('city') or '').casefold()==args.city.casefold()
                     and all(t in re.findall(r'\w+',(v.get('name') or '').casefold()) for t in terms)]
            if not matches: return [],now_iso()
            params['venue.id']=','.join(str(v['id']) for v in matches[:3])
        if args.query: params['q'] = args.query
        if args.type != 'any': params['taxonomies.name'] = args.type
        payload, fetched = await self.request('events',params)
        # The events q endpoint does not reliably match venue names. Resolve
        # matching venues explicitly when it returns no events, then query their
        # IDs while retaining the user's dates, city, type, ordering and limit.
        if args.query.strip() and not payload.get('events') and 'venue.id' not in params:
            venues, _ = await self.request('venues', {'q':args.query.strip(),'city':args.city,'per_page':10})
            terms = re.findall(r'\w+', args.query.casefold())
            matches = [v for v in venues.get('venues', [])
                       if terms and all(t in re.findall(r'\w+', (v.get('name') or '').casefold()) for t in terms)
                       and (v.get('city') or '').casefold() == args.city.casefold()]
            if matches:
                venue_params = {k:v for k,v in params.items() if k != 'q'}
                venue_params['venue.id'] = ','.join(str(v['id']) for v in matches[:3])
                payload, fetched = await self.request('events',venue_params)
                params=venue_params
        total=payload.get('meta',{}).get('total')
        records=list(payload.get('events',[]))
        for page in range(2,4):
            if len(payload.get('events',[]))<100: break
            payload,_=await self.request('events',{**params,'page':page})
            records.extend(payload.get('events',[]))
        # Retrieve favorite and related artists independently so chronological caps cannot hide them.
        if planning and not args.query:
            for artist in list(args.favorite_artists)+list(related_artists):
                favorite_params={**params,'q':artist,'per_page':100}
                favorites,_=await self.request('events',favorite_params)
                records.extend(favorites.get('events',[]))
        records=list({r['id']:r for r in records}.values())
        return SearchRecords(records,total,(total>len(records)) if isinstance(total,int) else len(records)>=300), fetched

    async def detail(self, event_id):
        if self.mode == 'sample':
            event = next((r for r in sample_records() if r['id'] == event_id), None)
            if not event: raise DataError('Event not found.')
            return event, now_iso()
        return await self.request(f'events/{event_id}',{})
