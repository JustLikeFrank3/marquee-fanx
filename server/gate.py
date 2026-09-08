"""Fail-closed verification of complete, event-bound canonical statements.

Free-form prose is intentionally not granted PASS based on regex extraction.
Every nonempty line must match a complete server-generated statement. This makes
scope explicit and prevents swapped events, negation, and unexamined additions.
"""
import re
from decimal import Decimal

LIMITS = 'Checks only the complete event statements listed here; not opinions, seat availability, fees, or sightlines.'

def dollars(value):
    return f'${Decimal(str(value)):.2f}'

def statements(event, party_size):
    prefix = f"[Event {event['event_id']}]"
    facts = []
    def fact(field, text, derived=False):
        facts.append({'event_id':event['event_id'], 'field':field,'claim':f'{prefix} {text}',
                      'status':'derived' if derived else 'supported','fetched_at':event['fetched_at']})
    fact('title', f"Event: {event['title']}.")
    fact('venue', f"Venue: {event['venue_name']}, {event['city']}, {event['state']}.")
    fact('datetime', f"Local date: {event['date'] or 'TBD'}; local time: {event['time'] or 'TBD'}.")
    if event['lowest_price'] is not None:
        fact('lowest_price',f"Lowest listing statistic: {dollars(event['lowest_price'])}.")
        total = Decimal(str(event['lowest_price']))*party_size
        fact('estimated_cost', f"Estimated total for {party_size}: {dollars(total)} (lowest listing statistic × party size; not a ticket offer).",True)
    else:
        fact('lowest_price','Price unavailable.')
    if event['listing_count'] is not None:
        fact('listing_count',f"Listing count: {event['listing_count']}.")
    if event.get('performers'):
        fact('performers',f"Performers: {', '.join(event['performers'])}.")
    for genre in event.get('genres',[]):
        fact('genre',f"Source genre tag for {genre['performer']}: {genre['name']}.")
    return facts

def verify(text, evidence):
    allowed, events = {}, {}
    for item in evidence:
        event = item['event']
        events[event['event_id']] = event
        for fact in statements(event,item['party_size']):
            allowed[fact['claim']] = fact
    checked, unsupported = [], []
    for line in (s.strip() for s in text.splitlines() if s.strip()):
        if line in allowed:
            checked.append(allowed[line])
            continue
        match = re.match(r'\[Event (\d+)\]',line)
        event = events.get(int(match[1])) if match else None
        reason = 'Outside supported statement format. Use the supplied evidence statements; this prose has not been verified.'
        closest = None
        if re.search(r'\b(section|row|seat)\s+[A-Z0-9]+',line,re.I):
            reason = 'Seat, row, and section availability are not supplied by the public event API.'
        elif match and not event:
            reason = 'This event is not in the supplied evidence.'
        elif event:
            reason = 'Statement does not match this event and field in the supplied evidence.'
            same_field = line.split(':',1)[0]+':'
            closest = next((s for s in allowed if s.startswith(same_field)),None)
        unsupported.append({'claim':line,'reason':reason,'closest_supported':closest})
    passed = bool(checked) and not unsupported
    mode = 'SAMPLE DATA' if any(e['event']['mode']=='sample' for e in evidence) else 'SEATGEEK DATA'
    return {'verdict':'PASS' if passed else 'FAIL','claims_checked':len(checked)+len(unsupported),
            'facts':checked,'unsupported':unsupported,'limits':LIMITS,
            'report':f"{'VERIFIED STATEMENTS' if passed else 'NOT VERIFIED'} · {len(checked)} supported, {len(unsupported)} unsupported · {mode}.",
            'fetched_at':min(e['event']['fetched_at'] for e in evidence)}
