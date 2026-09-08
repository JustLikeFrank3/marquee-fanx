import type {Event} from './types';
const escape=(s:string)=>s.replaceAll('\\','\\\\').replaceAll('\n','\\n').replaceAll(',','\\,').replaceAll(';','\\;').replaceAll('\r','');
export function calendarText(e:Event){
  if(!e.date)throw Error('The event date is not confirmed yet.');
  const date=e.date.replaceAll('-','');
  const zone=e.timezone&&/^[A-Za-z_]+(?:\/[A-Za-z_+-]+)+$/.test(e.timezone)?`;TZID=${e.timezone}`:'';
  const start=e.time?`DTSTART${zone}:${date}T${e.time.replace(':','')}00`:`DTSTART;VALUE=DATE:${date}`;
  const description=`${e.time?'Venue local time. End time not supplied.':'Time TBD; saved as an all-day reminder.'} Confirm details on SeatGeek before attending.${e.mode==='sample'?' FICTIONAL DEMO EVENT.':''}${e.url?' '+e.url:''}`;
  const lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Marquee//Event Discovery//EN','BEGIN:VEVENT',`UID:${e.mode}-${e.event_id}@marquee.local`,`DTSTAMP:${new Date().toISOString().replace(/[-:]/g,'').replace(/\.\d{3}/,'')}`,start,`SUMMARY:${escape(e.title)}`,`LOCATION:${escape(`${e.venue_name}, ${e.city}, ${e.state}`)}`,`DESCRIPTION:${escape(description)}`,'END:VEVENT','END:VCALENDAR'];
  // RFC 5545 line folding is measured in UTF-8 bytes.
  return lines.map(line=>{let out='',size=0;for(const ch of line){const len=new TextEncoder().encode(ch).length;if(size+len>75){out+='\r\n ';size=1;}out+=ch;size+=len;}return out;}).join('\r\n')+'\r\n';
}
export function downloadCalendar(e:Event){
  const url=URL.createObjectURL(new Blob([calendarText(e)],{type:'text/calendar;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=`marquee-${e.event_id}.ics`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export function mapsUrl(e:Event){return 'https://www.google.com/maps/search/?api=1&query='+encodeURIComponent(`${e.venue_name}, ${e.city}, ${e.state}`);}
export type SavedEvent=Pick<Event,'event_id'|'title'|'venue_name'|'city'|'date'|'mode'>;
const key='marquee-shortlist-v1';
export function readSaved():SavedEvent[]{try{const items=JSON.parse(localStorage.getItem(key)||'[]');return Array.isArray(items)?items.filter(e=>Number.isSafeInteger(e.event_id)&&typeof e.title==='string'&&typeof e.venue_name==='string'&&typeof e.city==='string'&&(e.date===null||typeof e.date==='string')&&['live','sample'].includes(e.mode)).slice(0,30):[];}catch{return [];}}
export function writeSaved(items:SavedEvent[]){localStorage.setItem(key,JSON.stringify(items));}
