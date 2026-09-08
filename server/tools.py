from decimal import Decimal
from datetime import date
import re
from .models import INPUTS
from .data import normalize, SearchRecords
from .genres import labels, matches, query_genres
from .genres import canonical as canonical_name
from .gate import statements, verify

DESCRIPTIONS = {
    'nearby_places':'Find real restaurants, bars and parking near an event venue. Supply a real event_id from event tools. Returns up to four listings per category, straight-line distances, and map links. No confirmed opening hours, prices, parking access, spaces, or walking times. Use for a park-once night-out plan.',
    'search_events':'Search up to 300 candidates and return a date-balanced slice. Read coverage and scope: results are not necessarily exhaustive. query is an artist/event/venue name, NEVER genre words. Put genre requests in genres. Matches source performer tags (OR). Missing tags are unknown. Read genre_coverage; never infer citywide absence from no tagged matches.',
    'event_details':'Get a public event summary and evidence. No individual seat inventory or native section imagery is available.',
    'compare_events':'Compare two or three events using their own evidence. Cheapest is among these events by lowest listing statistic only.',
    'plan_night':'Search up to 300 broad candidates plus separate favorite-artist queries across the date range. Filter by genres (source performer tags, OR), city, venue_query, keyword, type and weekdays (Monday=0). Rank favorite_artists matches first, then balance remaining choices across dates. Set include_related=true to also search artists Last.fm lists as similar to favorite_artists and to order alternatives by overlap with the favorites\u2019 Last.fm top tags; those results are attributed related discoveries, never favorites or invented similarities. Use exclude_event_ids to replace picks the user rejected. Return shortlist_size (1\u201310). Favorites are soft preferences; other results are explicitly alternatives. Optional budget excludes known over-budget events; unknown prices remain unassessed.',
    'verify_plan':'Verify exact canonical statement lines returned by data tools against session evidence. Free-form prose fails closed. Before presenting a plan, verify its statements and include the report. Does not verify seat availability or opinions.'}

def definitions():
    return [{'name':name,'description':DESCRIPTIONS[name],'inputSchema':model.model_json_schema()} for name,model in INPUTS.items()]

class ToolService:
    def __init__(self, source, store):
        self.source, self.store = source, store
        from .places import PlacesSource
        from .lastfm import SimilarSource
        self.places = PlacesSource()
        self.lastfm = SimilarSource()

    def result(self, token, records, fetched, party=2):
        events, handles, facts = [], [], []
        for raw in records:
            event = normalize(raw,fetched,self.source.mode)
            handle = self.store.add(token,event,raw,party)
            event['evidence_id'] = handle
            event['facts'] = [{**f,'evidence_id':handle} for f in statements(event,party)]
            events.append(event); handles.append(handle); facts.extend(event['facts'])
        return {'events':events,'evidence_ids':handles,'source':'Synthetic demo data' if self.source.mode=='sample' else 'Event data powered by SeatGeek',
                'mode':self.source.mode,'statements':'\n'.join(f['claim'] for f in facts)}

    async def call(self, name, args, token):
        self.store.session(token)
        if name not in INPUTS: raise ValueError('Unknown tool.')
        values = INPUTS[name].model_validate(args)
        if name == 'nearby_places':
            raw,_ = await self.source.detail(values.event_id)
            return await self.places.search(raw,self.source.mode,values)
        if name == 'verify_plan':
            return verify(values.text,self.store.get(token,values.evidence_ids))
        if name in ('search_events','plan_night'):
            requested=list(values.genres)
            detected=query_genres(values.query)
            if detected:
                requested=list(dict.fromkeys(requested+detected))
                values=values.model_copy(update={'query':''})
            if requested and values.type=='any':
                values=values.model_copy(update={'type':'concert'})
            related_info, attribution = None, {}
            tag_info, profile = None, {}
            if name=='plan_night' and values.include_related and values.favorite_artists:
                related_info = await self.lastfm.similar(values.favorite_artists)
                seeds={canonical_name(a) for a in values.favorite_artists}
                for seed,rows in related_info['seeds'].items():
                    for row in rows:
                        key=canonical_name(row['name'])
                        if not key or key in seeds: continue
                        if key not in attribution or (row['match'] or 0)>(attribution[key]['match'] or 0):
                            attribution[key]={'name':row['name'],'seed':seed,'match':row['match']}
                attribution=dict(sorted(attribution.items(),key=lambda kv:-(kv[1]['match'] or 0))[:10])
                tag_info = await self.lastfm.top_tags(values.favorite_artists)
                for rows in tag_info['seeds'].values():
                    for row in rows:
                        key=canonical_name(row['name'])
                        if key: profile[key]=profile.get(key,0)+row['count']
            related_names=[a['name'] for a in attribution.values()]
            records,fetched = await self.source.search(values,related_names)
            if name=='plan_night' and values.exclude_event_ids:
                excluded=set(values.exclude_event_ids)
                records=SearchRecords([r for r in records if r['id'] not in excluded],
                                      getattr(records,'total',None),getattr(records,'truncated',False))
            searched = len(records)
            total=getattr(records,'total',None)
            truncated=getattr(records,'truncated',searched>=300)
            candidate_dates=sorted({r.get('datetime_local','')[:10] for r in records if r.get('datetime_local')})
            tagged=sum(bool(labels(r)) for r in records)
            if requested:
                records=[r for r in records if matches(r,requested)]
            genre_matches=len(records)
            priced = sum(normalize(r,fetched,self.source.mode)['lowest_price'] is not None for r in records)
            if name == 'plan_night':
                records = [r for r in records if not normalize(r,fetched,self.source.mode)['date_tbd']]
                if values.weekdays:
                    records=[r for r in records if date.fromisoformat(r['datetime_local'][:10]).weekday() in values.weekdays]
                def canonical(text): return ' '.join(re.findall(r'\w+',text.casefold()))
                def matched(raw):
                    performers=[canonical(p.get('name','')) for p in raw.get('performers',[])]
                    title=' '+canonical(raw.get('title',''))+' '
                    return [a for a in values.favorite_artists if canonical(a) in performers or ' '+canonical(a)+' ' in title]
                def related_matched(raw):
                    performers=[canonical(p.get('name','')) for p in raw.get('performers',[])]
                    title=' '+canonical(raw.get('title',''))+' '
                    return sorted((a for k,a in attribution.items() if k in performers or ' '+k+' ' in title),key=lambda a:-(a['match'] or 0))
                if values.budget_usd is not None:
                    records = [r for r in records if (e:=normalize(r,fetched,self.source.mode))['lowest_price'] is None
                               or Decimal(str(e['lowest_price']))*values.party_size <= Decimal(str(values.budget_usd))]
                records.sort(key=lambda r: (-len(matched(r)),not related_matched(r),values.budget_usd is not None and normalize(r,fetched,self.source.mode)['lowest_price'] is None,
                                           r.get('datetime_local') or '',r['id']))
                favorites=[r for r in records if matched(r)]
                related=[r for r in records if not matched(r) and related_matched(r)]
                others=[r for r in records if not matched(r) and not related_matched(r)]
                # Coarse tags order ties only; specific tags like doom metal decide affinity.
                COARSE={'rock','pop','electronic','indie','alternative'}
                def overlap(raw):
                    keys={canonical(g['name']) for g in labels(raw)}|{canonical(g['slug']) for g in labels(raw)}
                    return sorted((k for k in keys if k in profile),key=lambda k:-profile[k])
                def affinity(raw):
                    hits=overlap(raw)
                    return (sum(profile[k] for k in hits if k not in COARSE),sum(profile[k] for k in hits if k in COARSE))
                buckets={}
                for raw in others: buckets.setdefault(raw['datetime_local'][:10],[]).append(raw)
                if profile:
                    for bucket in buckets.values(): bucket.sort(key=affinity,reverse=True)
                selected=(favorites+related)[:values.shortlist_size]
                while len(selected)<values.shortlist_size and any(buckets.values()):
                    for bucket in buckets.values():
                        if bucket and len(selected)<values.shortlist_size: selected.append(bucket.pop(0))
                records=selected
            if name=='search_events':
                buckets={day:[] for day in candidate_dates}
                for raw in records: buckets.setdefault((raw.get('datetime_local') or '')[:10],[]).append(raw)
                selected=[]
                while len(selected)<values.limit and any(buckets.values()):
                    for bucket in buckets.values():
                        if bucket and len(selected)<values.limit: selected.append(bucket.pop(0))
                records=selected
            result = self.result(token,records,fetched,getattr(values,'party_size',2))
            result['coverage']={'catalog_total':total,'candidates_considered':searched,'candidate_cap':300,
                                'candidate_truncated':truncated,'returned':len(records),'candidate_dates':candidate_dates,
                                'returned_dates':sorted({e['date'] for e in result['events'] if e['date']}),
                                'date_from':str(values.date_from),'date_to':str(values.date_to),'exhaustive':not truncated and len(records)==searched}
            if name=='search_events':
                result['scope']=f'Showing {len(records)} of {searched} retrieved candidates, balanced across event dates, for {values.date_from} through {values.date_to}. '
                result['scope']+=f'Catalog total: {total if total is not None else "not supplied"}. '
                result['scope']+=('The 300-candidate cap was reached; later dates may be missing. Narrow the date range.' if truncated else 'This displayed selection is not an exhaustive list.' if len(records)<searched else 'All retrieved candidates are shown.')
            if name == 'plan_night':
                result['scope'] = f'Considered {searched} candidates across the selected dates (broad search cap: 300, plus targeted favorite-artist searches). '+('Favorite-artist matches ranked first; remaining choices balanced across dates.' if values.favorite_artists else 'No favorite artists supplied; choices balanced across dates.')
                if truncated: result['scope']+=' Candidate cap reached; narrow the city, venue, or dates for better coverage.'
                if values.venue_query: result['scope']+=f' Venue filter: {values.venue_query}.'
                if values.budget_usd is not None:
                    result['scope'] += ' Known over-budget events excluded; unknown prices are not confirmed within budget.'
                for event,raw in zip(result['events'],records):
                    event['budget_status'] = ('not_requested' if values.budget_usd is None else 'unknown' if event['lowest_price'] is None else 'within_estimate')
                    event['why'] = f"{event['title']} at {event['venue_name']} on {event['date']} matches this event search."
                    related_hits=[] if matched(raw) else related_matched(raw)
                    if values.favorite_artists and not matched(raw) and not related_hits: event['why']='Alternative: no requested favorite artist matched this event. '+event['why']
                    if related_hits:
                        best=related_hits[0]
                        score='' if best['match'] is None else f" (match {best['match']})"
                        event['why']=f"Related discovery: Last.fm lists {best['name']} as similar to your favorite {best['seed']}{score}. "+event['why']
                    if matched(raw): event['why']='Matches your favorite artist: '+', '.join(matched(raw))+'. '+event['why']
                    if profile and not matched(raw) and not related_hits:
                        hits=[k for k in overlap(raw) if k not in COARSE][:3]
                        if hits: event['why']+=' Its source genre tags overlap your favorites\u2019 Last.fm top tags: '+', '.join(hits)+'.'
                if searched and not priced:
                    result['scope'] += ' Prices are not supplied; this is an event shortlist, not a priced offer.'
            result['scope']=f'{values.city}, {values.date_from} through {values.date_to}. '+result['scope']
            result['criteria']=values.model_dump(mode='json') | {'genres':requested}
            if requested:
                result['genre_coverage']={'requested':requested,'tagged_candidates':tagged,'untagged_candidates':searched-tagged,'matching_candidates':genre_matches}
                result['scope']+=' Genre filter: '+', '.join(requested)+f'. {genre_matches} of {searched} candidates matched source tags; {searched-tagged} untagged. Not exhaustive.'
            if name=='plan_night' and values.favorite_artists:
                found=[a for a in values.favorite_artists if any(a in matched(r) for r in records)]
                missing=[a for a in values.favorite_artists if a not in found]
                result['missing_favorites']=missing
                if missing: result['scope']+=' Requested artists absent from this selection: '+', '.join(missing)+'. Check the date range or search those artists directly; other results are alternatives.'
            if name=='plan_night' and values.exclude_event_ids:
                result['scope']+=' Excluded at your request: event '+', '.join(str(x) for x in values.exclude_event_ids)+'.'
            if name=='plan_night' and values.include_related:
                if not values.favorite_artists:
                    result['scope']+=' Related-artist discovery needs favorite artists; none were supplied.'
                elif related_info['status']=='unconfigured':
                    result['scope']+=' Related-artist discovery is unavailable: Last.fm similarity is not configured on this server.'
                elif related_info['status']=='error':
                    result['scope']+=' Last.fm similarity lookup failed; this shortlist shows favorites and alternatives only.'
                else:
                    result['scope']+=f' Related-artist discovery via Last.fm searched {len(related_names)} similar artists.' if related_names else ' Last.fm returned no similar artists for the requested favorites.'
                    if related_info['status']=='partial':
                        result['scope']+=' Last.fm lookup failed for: '+', '.join(related_info['failed_seeds'])+'.'
                    if profile:
                        result['scope']+=' Alternatives ordered by source-tag overlap with your favorites\u2019 Last.fm top tags.'
                result['related_discovery']={'status':related_info['status'] if related_info else 'no_seeds',
                    'source':(related_info or {}).get('source','Last.fm artist.getSimilar'),
                    'fetched_at':(related_info or {}).get('fetched_at'),
                    'seeds':(related_info or {}).get('seeds',{}),
                    'failed_seeds':(related_info or {}).get('failed_seeds',[]),
                    'searched_artists':[{'name':a['name'],'similar_to':a['seed'],'match':a['match']} for a in attribution.values()],
                    'note':'Last.fm similarity is a recommendation signal, not a verified concert fact.'}
            result['pricing_available'] = bool(priced)
            return result
        ids = [values.event_id] if name == 'event_details' else values.event_ids
        results = []
        for event_id in ids:
            raw,fetched = await self.source.detail(event_id)
            results.append(self.result(token,[raw],fetched))
        combined = {**results[0], 'events':sum((r['events'] for r in results),[]),
                    'evidence_ids':sum((r['evidence_ids'] for r in results),[]),
                    'statements':'\n'.join(r['statements'] for r in results)}
        if name == 'compare_events':
            priced = [e for e in combined['events'] if e['lowest_price'] is not None]
            combined['cheapest_by_lowest_price'] = min(priced,key=lambda e:e['lowest_price'])['event_id'] if priced else None
        return combined
