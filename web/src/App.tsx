import {useEffect,useRef,useState} from 'react';
import Planner from './Planner';
import Nearby,{NearbyPlan} from './Nearby';
import type {NearbyData} from './Nearby';
import {call,rpc,startSession} from './api';
import {browserContext,registerBridge} from './bridge';
import {downloadCalendar,mapsUrl,readSaved,writeSaved} from './event-actions';
import type {SavedEvent} from './event-actions';
import type {Event,Results,Report,Search} from './types';

const money=(n:number|null)=>n===null?'Unavailable':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(n);
const dateLabel=(e:Event)=>e.date?new Date(e.date+'T12:00:00').toLocaleDateString('en-US',{weekday:'short',month:'short',day:'numeric'}):'Date TBD';
const timeLabel=(e:Event)=>e.time?new Date('2000-01-01T'+e.time).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'}):'Time TBD';
const iso=(d:Date)=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const today=new Date(),later=new Date(today);later.setDate(today.getDate()+30);
const defaults:Search={query:'',city:'Atlanta',date_from:iso(today),date_to:iso(later),type:'any',limit:9};

function Artwork({event,large=false}:{event:Event;large?:boolean}){
  return <div className={`art art-${event.event_id%6} ${large?'large':''}`}>
    {event.artwork_url?<img src={event.artwork_url} alt="" loading="lazy" onError={e=>{e.currentTarget.style.display='none';}}/>:<><span className="poster-kicker">{event.mode==='sample'?'MARQUEE / SAMPLE SERIES':'LIVE / ON STAGE'}</span><strong>{event.title}</strong><span className="poster-bottom">{event.city.toUpperCase()} <span>↗</span></span><div className="art-disc" aria-hidden="true"/></>}
    <span className="type-tag">{event.kind.replaceAll('_',' ')}</span>
  </div>;
}

export default function App(){
  const [nearby,setNearby]=useState<NearbyData|null>(null);
  const [saved,setSaved]=useState<SavedEvent[]>(readSaved),[useBudget,setUseBudget]=useState(false);
  const [artistPreferences,setArtistPreferences]=useState(''),[venuePreference,setVenuePreference]=useState(''),[preferredDays,setPreferredDays]=useState<number[]>([]),[shortlistSize,setShortlistSize]=useState(3),[includeRelated,setIncludeRelated]=useState(false);
  const preferences={favorite_artists:artistPreferences.split(',').map(a=>a.trim()).filter(Boolean),include_related:includeRelated,venue_query:venuePreference,weekdays:preferredDays,shortlist_size:shortlistSize};
  const [submitted,setSubmitted]=useState('');
  const [search,setSearch]=useState(defaults),[budget,setBudget]=useState(120),[party,setParty]=useState(2);
  const [events,setEvents]=useState<Event[]>([]),[selected,setSelected]=useState<Event[]>([]),[pick,setPick]=useState<Event|null>(null);
  const [mode,setMode]=useState('sample'),[busy,setBusy]=useState(''),[error,setError]=useState(''),[loaded,setLoaded]=useState(false);
  const [detail,setDetail]=useState<Event|null>(null),[report,setReport]=useState<Report|null>(null),[text,setText]=useState(''),[handles,setHandles]=useState<string[]>([]);
  const [factsOpen,setFactsOpen]=useState(false),[agent,setAgent]=useState('Checking agent support…'),[scope,setScope]=useState('');
  const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLElement|null>(null),latest=useRef(0);
  function saveEvent(e:Event){
    const exists=saved.some(s=>s.event_id===e.event_id&&s.mode===e.mode);
    if(!exists&&saved.length>=30){setError('Your shortlist has 30 events. Remove one before saving another.');return;}
    const next=exists?saved.filter(s=>s.event_id!==e.event_id||s.mode!==e.mode):[...saved,{event_id:e.event_id,title:e.title,venue_name:e.venue_name,city:e.city,date:e.date,mode:e.mode}];
    try{writeSaved(next);setSaved(next);}catch{setError('This browser could not save your shortlist.');}
  }
  function removeSaved(e:SavedEvent){try{const next=saved.filter(s=>s.event_id!==e.event_id||s.mode!==e.mode);writeSaved(next);setSaved(next);}catch{setError('This browser could not update your shortlist.');}}
  async function openSaved(e:SavedEvent){setError('');try{const r=await call<Results>('event_details',{event_id:e.event_id});setDetail(r.events[0]);}catch(err){setError((err as Error).message);}}


  function useEvidence(result:Results){setHandles(result.evidence_ids);setText(result.statements);setReport(null);setMode(result.mode);}
  async function verifyText(value:string,ids=handles){
    setBusy('verify');setError('');
    try{setReport(await call<Report>('verify_plan',{text:value,evidence_ids:ids}));setFactsOpen(true);}catch(e){setError((e as Error).message);}finally{setBusy('');}
  }
  const formSignature=JSON.stringify({search,preferences,budget,party,useBudget});
  async function run(name='plan_night',criteria=search){
    const request=++latest.current;setBusy(name);setError('');
    try{
      const args=name==='plan_night'?{...criteria,...preferences,budget_usd:useBudget?budget:null,party_size:party}:criteria;
      const result=await call<Results>(name,args);
      if(request!==latest.current)return;
      setSubmitted(formSignature);setEvents(result.events);setSelected([]);setLoaded(true);setScope(result.scope||'');
      const candidate=name==='plan_night'?result.events[0]:null;setPick(candidate||null);
      if(candidate){const ids=[candidate.evidence_id],value=candidate.facts.map(f=>f.claim).join('\n');setHandles(ids);setText(value);setReport(await call<Report>('verify_plan',{text:value,evidence_ids:ids}));}
      else {setHandles(result.evidence_ids);setText('');setReport(null);}
    }catch(e){if(request===latest.current)setError((e as Error).message);}finally{if(request===latest.current)setBusy('');}
  }
  useEffect(()=>{
    let active=true,cleanup=()=>{};
    startSession().then(s=>{if(active)setMode(s.mode);}).catch(e=>{if(active)setError(e.message);});
    run('search_events');
    (async()=>{
      try{
        const {tools}=await rpc('tools/list');
        if(!active)return;
        const result=await registerBridge(browserContext(),tools,async(name,args)=>{
          const result=await rpc('tools/call',{name,arguments:args});
          if(result.isError)throw Error(result.content[0].text);
          const value=JSON.parse(result.content[0].text);
          if(name==='verify_plan'){setReport(value);setText(String(args.text));setHandles(args.evidence_ids as string[]);setFactsOpen(true);}
          else if(name==='nearby_places'){setNearby(value);}
          else if(name==='compare_events'){setSelected(value.events);useEvidence(value);}
          else if(name==='event_details'){setDetail(value.events[0]);useEvidence(value);}
          else{setEvents(value.events);setLoaded(true);setSelected([]);setPick(name==='plan_night'?value.events[0]||null:null);useEvidence(value);setScope(value.scope||'');}
          return value;
        });
        if(!active){result.cleanup();return;}cleanup=result.cleanup;setAgent(result.count?`Agent connected \u00b7 ${result.count} tools`:'WebMCP ready \u00b7 no browser agent');
      }catch{if(active)setAgent('WebMCP ready \u00b7 no browser agent');}
    })();
    return ()=>{active=false;cleanup();};
  },[]);
  useEffect(()=>{if(detail&&!dialog.current?.open){trigger.current=document.activeElement as HTMLElement;dialog.current?.showModal();}else if(!detail&&dialog.current?.open){dialog.current.close();trigger.current?.focus();}},[detail]);

  function toggle(e:Event){setSelected(old=>old.some(x=>x.event_id===e.event_id)?old.filter(x=>x.event_id!==e.event_id):old.length<3?[...old,e]:old);}
  async function compare(){setBusy('compare');setError('');try{const result=await call<Results>('compare_events',{event_ids:selected.map(e=>e.event_id)});setSelected(result.events);useEvidence(result);document.getElementById('compare')?.scrollIntoView({behavior:'smooth'});}catch(e){setError((e as Error).message);}finally{setBusy('');}}
  async function open(e:Event){setDetail(e);setError('');try{const result=await call<Results>('event_details',{event_id:e.event_id});setDetail(old=>old?.event_id===e.event_id?result.events[0]:old);}catch(err){setError((err as Error).message);}}
  const update=(key:keyof Search,value:string)=>setSearch({...search,[key]:value});
  function inject(kind:'price'|'seat'){
    const e=pick||selected[0]||events[0];if(!e)return;
    const lines=e.facts.map(f=>f.claim),value=kind==='price'?lines.filter(l=>!l.includes('Lowest listing statistic:')&&!l.includes('Price unavailable.')).join('\n')+`\n[Event ${e.event_id}] Lowest listing statistic: $48.00.`:lines.join('\n')+`\n[Event ${e.event_id}] Seats available in section 112.`;
    setText(value);setHandles([e.evidence_id]);verifyText(value,[e.evidence_id]);
  }
  return <>
    <header><a className="wordmark" href="#">Marquee</a><span className="eyebrow mode">{mode==='sample'?'SAMPLE DATA / REAL VERIFICATION':'LIVE EVENT DATA'}</span><span className={`agent ${agent.includes('Agent connected')?'connected':''}`} title="This page exposes its event tools to browser-embedded AI agents over WebMCP. Everything works without one; an agent-capable browser can drive the page directly."><i/>{agent}</span></header>
    <main>
      <Planner context={{...search,...preferences,budget_usd:useBudget?budget:null,party_size:party}} onResults={(result,checked)=>{++latest.current;setBusy('');setEvents(result.events);setSelected([]);setLoaded(true);setScope(result.scope||'');setPick(result.events[0]||null);useEvidence(result);setReport(checked);}}/>
      {nearby&&<section className="wrap"><NearbyPlan key={nearby.fetched_at} data={nearby}/></section>}
      <section className="hero wrap"><div className="hero-heading"><div><p className="eyebrow orange">GOOD NIGHTS START HERE</p><h1>A night out,<br/><em>found.</em></h1></div><p className="lede">Find your kind of live. <br/>Compare the options.<br/><span>Check the facts behind the pick.</span></p></div>
        <form onSubmit={e=>{e.preventDefault();run();}}>
          <div className="searchbox"><span aria-hidden="true">⌕</span><input aria-label="Artist, event or venue" placeholder="An artist, an event, a place. What sounds good?" value={search.query} onChange={e=>update('query',e.target.value)} maxLength={160}/><button className="accent" disabled={!!busy}>Find my night <span>↗</span></button></div>
          <div className="controls"><label>City<input value={search.city} onChange={e=>update('city',e.target.value)} required maxLength={100}/></label><label>From<input type="date" value={search.date_from} onChange={e=>update('date_from',e.target.value)} required/></label><label>Through<input type="date" min={search.date_from} value={search.date_to} onChange={e=>update('date_to',e.target.value)} required/></label><label>Optional budget · USD<input type="number" min="1" max="100000" disabled={!useBudget} value={budget} onChange={e=>setBudget(Number(e.target.value))} required/></label><label>Party size<select value={party} onChange={e=>setParty(Number(e.target.value))}>{Array.from({length:10},(_,i)=><option key={i} value={i+1}>{i+1} {i?'people':'person'}</option>)}</select></label><label>Type<select value={search.type} onChange={e=>update('type',e.target.value)}><option value="any">Anything live</option><option value="concert">Concerts</option><option value="sports">Sports</option><option value="theater">Theater</option></select></label></div>
          <details className="shortlist-preferences"><summary>Personalize your shortlist</summary><div className="controls"><label>Favorite artists · comma separated<input value={artistPreferences} onChange={e=>setArtistPreferences(e.target.value)} placeholder="Streetlight Manifesto, DJ Shadow" maxLength={1000}/></label><label>Venue filter<input value={venuePreference} onChange={e=>setVenuePreference(e.target.value)} placeholder="The Eastern" maxLength={100}/></label><label>Show me<select value={shortlistSize} onChange={e=>setShortlistSize(Number(e.target.value))}>{[3,5,10].map(n=><option key={n} value={n}>{n} events</option>)}</select></label></div><label>Genres · comma separated<input value={(search.genres||[]).join(",")} onChange={e=>setSearch({...search,genres:e.target.value.split(",")})} placeholder="punk rock, jazz" maxLength={300}/></label><div className="weekday-choices">{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((d,i)=><label key={d}><input type="checkbox" checked={preferredDays.includes(i)} onChange={()=>setPreferredDays(preferredDays.includes(i)?preferredDays.filter(v=>v!==i):[...preferredDays,i])}/>{d}</label>)}</div><label className="budget-option"><input type="checkbox" checked={includeRelated} onChange={e=>setIncludeRelated(e.target.checked)}/> Discover related artists similar to your favorites (via Last.fm)</label><p className="fine">These settings apply to both search buttons and the AI planner. No days selected means any day. Artists boost matches; venue and days filter results. Searches check up to 300 broad candidates plus separate searches for your favorite artists.{includeRelated?' Related discoveries use Last.fm similarity \u2014 a recommendation signal, not a verified fact \u2014 and appear in shortlists after favorite-artist matches.':''}</p></details><div className="under-search"><span>{mode==='sample'?'Fictional Atlanta events for exploring the demo.':'Event data powered by SeatGeek.'} Search matches event, artist, or venue keywords.</span><button type="button" className="text-button" disabled={!!busy||(useBudget&&budget<1)||party<1} onClick={()=>run('plan_night')}>Build my shortlist →</button></div>
        <label className="budget-option"><input type="checkbox" checked={useBudget} onChange={e=>setUseBudget(e.target.checked)}/> Apply optional budget to supplied prices</label><p className="fine budget-note">Unpriced events remain in your shortlist, clearly marked as unassessed. Known over-budget events are excluded when this option is on.</p></form>
      </section>
      <div className="wrap" aria-live="polite">{error&&<div role="alert" className="error"><strong>We couldn’t complete that request.</strong><p>{error}</p><button onClick={()=>run()} disabled={!!busy}>Try search again</button></div>}</div>
      <section className="wrap explore" aria-busy={busy==='search_events'||busy==='plan_night'}><div className="section-title"><div><p className="eyebrow orange">01 / EXPLORE</p><h2>{busy==='search_events'||busy==='plan_night'?'Finding your next night…':(events.length ? `${events.length} events in this selection.` : scope.includes('Genre filter:')?'No matching genre tags found.':'No events found.')}</h2></div><p>Compare who’s playing, where, and when.<br/>Pick up to three events to compare.</p></div>
        {loaded&&submitted&&submitted!==formSignature&&<p className="planner-notice" role="status">Search settings changed. These are previous results. Choose “Find my night” to update them.</p>}
        {scope&&<p className="planner-notice">{scope}</p>}
        {(busy==='search_events'||busy==='plan_night')?<div className="grid">{[0,1,2].map(i=><div key={i} className="skeleton"/>)}</div>:<div className="grid">{events.map(e=><article className={`card ${selected.some(s=>s.event_id===e.event_id)?'selected':''}`} key={e.event_id}><button className="art-button" aria-label={`Open details for ${e.title}`} onClick={()=>open(e)}><Artwork event={e}/></button><div className="card-body"><p className="eyebrow orange">{dateLabel(e)} · {timeLabel(e)} local</p><h3>{e.title}</h3><p className="venue">{e.venue_name} · {e.city}</p>{e.why&&<p className="fine">{e.why}</p>}<p className="fine">{e.genres?.length?"Source genres: "+[...new Set(e.genres.map(g=>g.name))].join(", "):"Genre tags not supplied"}</p><div className="price-row"><div><strong>{e.lowest_price===null?'Check tickets on SeatGeek':`From ${money(e.lowest_price)}`}</strong><small>{e.average_price===null?'':`avg ${money(e.average_price)} · `}{e.listing_count===null?'Pricing not supplied by this data source':`${e.listing_count.toLocaleString()} listings`}</small></div>{e.url&&<a href={e.url} target="_blank" rel="noreferrer" aria-label={`Open ${e.title} on SeatGeek`}>↗</a>}</div><div className="card-actions"><button onClick={()=>open(e)}>Details</button><button className={selected.some(s=>s.event_id===e.event_id)?'accent':''} aria-pressed={selected.some(s=>s.event_id===e.event_id)} disabled={selected.length===3&&!selected.some(s=>s.event_id===e.event_id)} onClick={()=>toggle(e)}>{selected.some(s=>s.event_id===e.event_id)?'✓ Comparing':'+ Compare'}</button></div></div></article>)}</div>}
        {loaded&&events.length>0&&events.every(e=>e.lowest_price===null)&&<p className="fine">Discover and shortlist these events now. Pricing is not supplied by this data source; price estimates will appear if a future data connection provides them.</p>}
        {loaded&&!events.length&&!busy&&<div className="empty"><span className="eyebrow">NO MATCHES THIS TIME</span><h3>{scope.includes('without price')?'Pricing is not available.':'Let’s widen the search.'}</h3><p>{scope||'Try another date, a different event type, or clear the keyword.'}{mode==='sample'?' Sample events are in Atlanta on the upcoming weekend.':''}</p><button onClick={()=>{setSearch(defaults);run('search_events',defaults);}}>Reset search fields</button></div>}
      </section>
      {selected.length>0&&<section className="compare-band" id="compare"><div className="wrap"><div className="section-title"><div><p className="eyebrow">02 / COMPARE</p><h2>{selected.length>1?'Side by side.':'One down. Pick another.'}</h2></div><button onClick={()=>setSelected([])}>Clear selection</button></div><div className="compare-grid">{selected.map(e=><article key={e.event_id}><button className="remove" aria-label={`Remove ${e.title}`} onClick={()=>toggle(e)}>×</button><h3>{e.title}</h3><dl><dt>When</dt><dd>{dateLabel(e)} · {timeLabel(e)}</dd><dt>Venue</dt><dd>{e.venue_name}</dd><dt>Performers</dt><dd>{e.performers?.join(", ")||"Not supplied"}</dd><dt>Lowest statistic</dt><dd>{money(e.lowest_price)}</dd><dt>Estimate for {party}</dt><dd className="estimate">{e.lowest_price===null?'Unavailable':`≈ ${money(e.lowest_price*party)}`}</dd><dt>Your budget</dt><dd>{!useBudget?'Not applied':e.lowest_price===null?'Not assessed — price unknown':e.lowest_price*party<=budget?'Within budget':`${money(e.lowest_price*party-budget)} over budget`}</dd></dl></article>)}</div><p className="fine">Estimate = lowest listing statistic × party size. It does not confirm availability, fees, or adjacent seats.</p><button className="accent" disabled={selected.length<2||!!busy} onClick={compare}>Load comparison evidence →</button></div></section>}
      {saved.length>0&&<section className="wrap saved-section"><p className="eyebrow orange">YOUR SAVED NIGHTS</p><h2>A shortlist worth keeping.</h2><p className="fine">Saved on this browser only. Open an event to refresh its details; dates may change.</p><div className="saved-grid">{saved.map(e=><article key={e.mode+e.event_id}><h3>{e.title}</h3><p>{e.venue_name} · {e.date||'Date TBD'}</p><div className="buttons"><button disabled={e.mode!==mode} onClick={()=>openSaved(e)}>Open event</button><button onClick={()=>removeSaved(e)}>Remove</button></div>{e.mode!==mode&&<small>Saved in {e.mode} mode</small>}</article>)}</div></section>}
      <section className="wrap evidence-section" id="evidence"><div className="recommendation"><p className="eyebrow orange">03 / WITH THE RECEIPTS</p><h2>{pick?pick.title:'A good pick deserves good evidence.'}</h2><p>{pick?`${pick.venue_name} · ${dateLabel(pick)} · ${timeLabel(pick)} local.`:'Use “Build my shortlist” for date-and-interest suggestions, or compare a few events and inspect their facts.'}</p>{pick?.why&&<p>{pick.why}</p>}{scope&&<p className="fine">{scope}</p>}{pick&&<button className="dark" onClick={()=>open(pick)}>Explore this event ↗</button>}<div className="demo-box"><span className="eyebrow">TRY THE VERIFICATION</span><p>Change a price or add an unsupported seat claim. These buttons test the real server checker.</p><div className="buttons"><button disabled={!events.length||!!busy} onClick={()=>inject('price')}>Try a $48 claim</button><button disabled={!events.length||!!busy} onClick={()=>inject('seat')}>Claim section 112</button></div></div></div>
        <div className="facts-panel"><button className="facts-toggle" aria-expanded={factsOpen} onClick={()=>setFactsOpen(!factsOpen)}>Check the facts <span>{factsOpen?'−':'+'}</span></button>{factsOpen&&<><div className={`verdict ${report?.verdict==='FAIL'?'fail':report?'pass':''}`} role="status">{report?.report||'Ready to check. Nothing verified yet.'}</div><div className="facts-content"><p className="fine">The checker accepts complete event statements shown below. Edited or additional prose must not be treated as verified.</p><label className="statement-label">Statements to verify<textarea rows={9} value={text} placeholder="Plan a night or load comparison evidence to start." onChange={e=>{setText(e.target.value);setReport(null);}} maxLength={8000}/></label><button className="dark" disabled={!text.trim()||!handles.length||!!busy} onClick={()=>verifyText(text)}>{busy==='verify'?'Checking…':'Verify these statements →'}</button>{report&&<><p className="eyebrow retrieved">Retrieved {new Date(report.fetched_at).toLocaleString()}</p>{report.unsupported.map((u,i)=><div className="unsupported" key={i}><strong>✕ {u.claim}</strong><p>{u.reason}</p>{u.closest_supported&&<p>Supported: {u.closest_supported}</p>}</div>)}{report.facts.map((f,i)=><div className="fact" key={i}><span>✓</span><div>{f.claim}<small>{f.status} · event {f.event_id} · {f.field}</small></div></div>)}<p className="fine">{report.limits}</p></>}</div></>}</div>
      </section>
    </main><footer className="wrap"><a className="wordmark" href="#">Marquee</a><p>Independent portfolio project. Not affiliated with SeatGeek.<br/>{mode==='sample'?'Fictional demo events. No tickets are offered.':<a href="https://seatgeek.com" target="_blank" rel="noreferrer">Event data powered by SeatGeek ↗</a>}</p><span className="eyebrow">FANS FIRST. FACTS ALWAYS.</span></footer>
    {selected.length>0&&<div className="tray"><span>{selected.length} of 3 selected</span><a href="#compare">Compare {selected.length} →</a></div>}
    <dialog ref={dialog} onCancel={()=>setDetail(null)} onClick={e=>{if(e.target===dialog.current)setDetail(null);}}><div className="drawer">{detail&&<><div className="drawer-top"><span className="eyebrow">EVENT DETAIL / {detail.kind}</span><button aria-label="Close details" onClick={()=>setDetail(null)}>×</button></div><div className="drawer-content"><p className="eyebrow orange">{dateLabel(detail)} · {timeLabel(detail)} local</p><h2>{detail.title}</h2><p>{detail.venue_name} · {detail.city}, {detail.state}</p><p className="fine">{detail.performers?.join(' · ')}</p><div className="buttons event-actions"><button onClick={()=>saveEvent(detail)}>{saved.some(e=>e.event_id===detail.event_id&&e.mode===detail.mode)?'✓ Saved — remove':'+ Save event'}</button><button disabled={!detail.date} onClick={()=>downloadCalendar(detail)}>Add to calendar</button><a className="button" href={mapsUrl(detail)} target="_blank" rel="noreferrer">View venue map ↗</a></div><Nearby key={detail.event_id} eventId={detail.event_id}/><Artwork event={detail}/><div className="seat-preview"><span className="eyebrow">EXPLORE THE VIEW</span><h3>Your night, from a different angle.</h3><p>{detail.seat_preview.reason}</p>{detail.url?<a className="button dark" href={detail.url} target="_blank" rel="noreferrer">Explore on SeatGeek ↗</a>:<span className="preview-unavailable">Section preview unavailable · sample event</span>}<small>Section imagery is representative, not a guarantee of an exact seat or sightline.</small></div><dl className="detail-facts"><div><dt>Lowest listing statistic</dt><dd>{money(detail.lowest_price)}</dd></div><div><dt>Estimate for {party}</dt><dd>{detail.lowest_price===null?'Unavailable':`≈ ${money(detail.lowest_price*party)}`}</dd></div><div><dt>Venue time zone</dt><dd>{detail.timezone||'Not supplied'}</dd></div><div><dt>Data retrieved</dt><dd>{new Date(detail.fetched_at).toLocaleString()}</dd></div></dl><p className="fine">Aggregate statistics. Estimated total is not a ticket offer.</p><button className="accent" onClick={()=>toggle(detail)} disabled={selected.length===3&&!selected.some(e=>e.event_id===detail.event_id)}>{selected.some(e=>e.event_id===detail.event_id)?'Remove from comparison':'+ Add to comparison'}</button></div></>}</div></dialog>
  </>;
}
