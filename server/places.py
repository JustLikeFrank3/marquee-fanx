"""Venue-anchored Azure Maps listings. No invented hours, rates, or availability."""
import asyncio
import math
import os
from urllib.parse import urlencode
import httpx
from .data import DataError, now_iso

def distance(a,b,c,d):
    x,y=math.radians(c-a),math.radians(d-b)
    h=math.sin(x/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(y/2)**2
    return round(6371000*2*math.asin(min(1,math.sqrt(h))))

def coordinates(value):
    try:
        lat,lon=float(value['lat']),float(value['lon'])
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:
            return None
        return lat,lon
    except (KeyError,TypeError,ValueError): return None

class PlacesSource:
    async def search(self, raw, mode, args):
        venue=raw.get('venue') or {}
        origin=coordinates(venue.get('location'))
        base={'event_id':raw['id'],'event_title':raw.get('title','Event'),'event_time':raw.get('datetime_local'), 'venue_name':venue.get('name','Venue'),'radius_m':args.radius_m,
              'policy_status':'unconfirmed',
              'policy_search_url':'https://www.google.com/search?'+urlencode({'q':f"{venue.get('name','')} {venue.get('city','')} official bag policy prohibited items"}),
              'source':'Azure Maps','fetched_at':now_iso(),'places':[],
              'limits':'Straight-line distances from the venue, not walking routes. Hours, food prices, parking rates, public access, and live space availability are not confirmed. Check the listing before travelling.'}
        if mode!='live' or origin is None:
            return {**base,'status':'unavailable','reason':'Real venue coordinates are required; nearby search is unavailable for this event.'}
        key=os.getenv('AZURE_MAPS_KEY')
        if not key: raise DataError('Nearby search needs the Marquee Azure Maps connection.')
        cats=['parking','restaurant','bar'] if args.category=='all' else [args.category]
        category_ids={'restaurant':'7315','bar':'9379004,9379006,9379007','parking':'7369002,7313'}
        async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
            async def find(category):
                try:
                    response=await client.get('https://atlas.microsoft.com/search/nearby/json',
                        params={'api-version':'1.0','subscription-key':key,'categorySet':category_ids[category],
                                'lat':origin[0],'lon':origin[1],'radius':args.radius_m,'limit':12})
                    response.raise_for_status()
                    rows=response.json().get('results',[])
                except (httpx.HTTPError,ValueError):
                    raise DataError('Nearby listings are temporarily unavailable. Try again shortly.') from None
                found=[]
                for row in rows:
                    pos=coordinates(row.get('position'))
                    name=(row.get('poi') or {}).get('name')
                    if not pos or not name: continue
                    meters=distance(*origin,*pos)
                    if meters>args.radius_m: continue
                    address=(row.get('address') or {}).get('freeformAddress','')
                    found.append({'place_id':row.get('id',name+address),'name':name,'category':category,
                        'address':address,'distance_m':meters,'latitude':pos[0],'longitude':pos[1],
                        'map_url':'https://www.google.com/maps/search/?'+urlencode({'api':1,'query':name+' '+address}),
                        'directions_url':'https://www.google.com/maps/dir/?'+urlencode({'api':1,'origin':f'{pos[0]},{pos[1]}','destination':f'{origin[0]},{origin[1]}','travelmode':'walking'}),
                        'hours':None,'price':None,'availability':None})
                return sorted(found,key=lambda p:p['distance_m'])[:4]
            groups=await asyncio.gather(*(find(c) for c in cats))
        return {**base,'status':'ok','places':[p for group in groups for p in group]}
