import {it,expect} from 'vitest';
import {calendarText,mapsUrl} from './event-actions';
import type {Event} from './types';
const event={event_id:1,title:'A, B; Live',venue_name:'The Eastern',city:'Atlanta',state:'GA',date:'2026-09-15',time:'20:00',timezone:'America/New_York',mode:'live',url:'https://seatgeek.com/event'} as Event;
it('exports the venue time zone without inventing an end time',()=>{
 const text=calendarText(event);expect(text).toContain('DTSTART;TZID=America/New_York:20260915T200000');
 expect(text).toContain('SUMMARY:A\\, B\\; Live');expect(text).not.toContain('DTEND');
});
it('exports TBD time as an explicitly described all-day reminder',()=>{
 const text=calendarText({...event,time:null});expect(text).toContain('DTSTART;VALUE=DATE:20260915');expect(text).toContain('Time TBD');
 expect(()=>calendarText({...event,date:null})).toThrow();
});
it('folds long UTF-8 lines and URL encodes the venue map search',()=>{
 const text=calendarText({...event,title:'🎸'.repeat(60)});
 expect(text.split('\r\n').every(line=>new TextEncoder().encode(line).length<=75)).toBe(true);
 expect(mapsUrl(event)).toContain('The%20Eastern%2C%20Atlanta%2C%20GA');
});
