import {NearbyPlan} from './Nearby';
import type {NearbyData} from './Nearby';
import {useEffect,useState} from 'react';
import {call} from './api';
import type {Results,Report,Search} from './types';

type Reply={nearby:NearbyData|null;reply:string;results:Results|null;report:Report|null;actions:{name:string;ok:boolean}[];model?:string|null};
type Provider={id:string;label:string;configured:boolean;available:boolean};
type Message={nearby?:NearbyData|null;role:'user'|'assistant';text:string;results?:Results|null;actions?:Reply['actions'];report?:Report|null;model?:string|null};
// Only surface notes that change what the reader does next; mechanics live in the disclosure.
function actionNotes(r:Results|null|undefined):string[]{
  if(!r)return[];
  const notes:string[]=[];
  if(r.missing_favorites?.length)notes.push(`${r.missing_favorites.join(', ')} ${r.missing_favorites.length>1?"aren't":"isn't"} playing in this range.`);
  if(r.events.length&&r.pricing_available===false)notes.push('Prices aren\u2019t available from this source.');
  if(r.genre_coverage)notes.push(`Not every show: ${r.genre_coverage.untagged_candidates} of ${r.coverage?.candidates_considered??r.genre_coverage.untagged_candidates+r.genre_coverage.tagged_candidates} candidates had no genre tags.`);
  else if(r.coverage&&!r.coverage.exhaustive)notes.push('This isn\u2019t every show in the range.');
  return notes;
}
function badge(report:Report|null|undefined):string{
  if(!report)return 'No facts checked';
  const good=report.claims_checked-report.unsupported.length;
  return `Facts verified ${good}/${report.claims_checked}`;
}
export default function Planner({context,onResults}:{context:Search&{budget_usd:number|null;party_size:number};onResults:(results:Results,report:Report|null)=>void}){
  const [configured,setConfigured]=useState<boolean|null>(null),[input,setInput]=useState(''),[modelLabel,setModelLabel]=useState('');
  const [providers,setProviders]=useState<Provider[]>([]),[provider,setProvider]=useState<'auto'|'local'|'cloud'>('auto');
  const [messages,setMessages]=useState<Message[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [reset,setReset]=useState(true);
  useEffect(()=>{
    let active=true;
    const check=()=>fetch('/api/chat/status').then(r=>{if(!r.ok)throw Error();return r.json();}).then(v=>{if(active){
      setConfigured(v.configured);setModelLabel(v.model||'');
      const list:Provider[]=v.providers||[];setProviders(list);
      // A pinned local provider must not survive the model going away.
      if(!list.find(x=>x.id==='local')?.available)setProvider(p=>p==='local'?'auto':p);
    }}).catch(()=>{if(active)setError('Could not check the AI connection. Refresh to retry.');});
    check();const timer=setInterval(check,30000);
    return()=>{active=false;clearInterval(timer);};
  },[]);
  async function send(){
    const message=input.trim();if(!message||busy)return;
    setBusy(true);setError('');
    try{
      const result=await call<Reply>('chat/message',{message,context,reset,provider});
      setMessages(prev=>[...prev,{role:'user',text:message},{role:'assistant',text:result.reply,actions:result.actions,report:result.report,nearby:result.nearby,results:result.results,model:result.model}].slice(-16) as Message[]);
      setInput('');setReset(false);
      if(result.model)setModelLabel(result.model);
      if(result.results)onResults(result.results,result.report);
    }catch(e){
      // Keep the failed prompt visible and editable so a transient error costs nothing.
      setMessages(prev=>[...prev,{role:'user',text:message}].slice(-16) as Message[]);
      setError((e as Error).message);
    }finally{setBusy(false);}
  }
  return <section className="wrap planner-section" aria-labelledby="planner-title">
    <div className="planner"><div className="planner-intro"><p className="eyebrow orange">MEET YOUR NIGHT-OUT ASSISTANT</p><h2 id="planner-title">Say what sounds good.</h2><p>Tell Marquee what you’re in the mood for. Ask follow-up questions, compare options, and find your next night out.</p><span className="eyebrow">{configured===null?'CHECKING CONNECTION':configured?'AI + EVENT TOOLS':'AI CONNECTION NEEDED'}</span>{modelLabel&&<span className="badge model-badge" title="The model currently answering the planner chat">{modelLabel}</span>}{providers.length>0&&<div className="provider-switch">{(['auto','local','cloud'] as const).map(p=>{const meta=providers.find(x=>x.id===p);const off=p==='local'&&!meta?.available;return <button key={p} type="button" disabled={busy||off} className={provider===p?'accent':''} aria-pressed={provider===p} title={off?(meta?.configured?'Local model is unreachable \u2014 start it, or use auto or cloud':'No local model is configured on this server'):p==='auto'?'Local when available, cloud otherwise':meta?.label} onClick={()=>setProvider(p)}>{p}{p==='local'&&<i className={`dot ${off?'':'up'}`} aria-hidden="true"/>}</button>;})}<small>{providers.find(x=>x.id==='local')?.available?'local model online':'local model offline'}</small></div>}</div>
    <div className="planner-conversation">
      {configured===false&&<p className="planner-notice">The AI planner is waiting for its model connection. You can use event search below in the meantime.</p>}
      {!messages.length&&<div className="planner-suggestions">{['Find concerts in Atlanta this weekend','What’s coming up at The Eastern?','Plan a night out with parking, dinner and a concert'].map(s=><button key={s} disabled={busy||!configured} onClick={()=>setInput(s)}>{s}</button>)}</div>}
      <div className="planner-messages" role="log" aria-label="Planner conversation" aria-live="polite">{messages.map((m,i)=><article className={`chat-message ${m.role}`} key={i}><span className="eyebrow">{m.role==='user'?'YOU':'MARQUEE \u00b7 AI'}</span><p>{m.text}</p>{m.role==='assistant'&&actionNotes(m.results).map((n,j)=><p key={j} className="chat-note">{n}</p>)}{m.role==='assistant'&&m.report&&m.report.verdict==='FAIL'&&<p className="planner-notice" role="alert">Some event facts in this reply could not be verified. Trust the event cards, not the prose.</p>}{m.role==='assistant'&&<details className="provenance"><summary>How this was found · <span className={m.report?.verdict==='PASS'?'badge pass':'badge'}>{badge(m.report)}</span></summary>{m.results?.scope&&<p>{m.results.scope}</p>}{m.model&&<p className="fine">Answered by {m.model}.</p>}{m.actions?.length?<div className="chat-actions">{m.actions.map((a,j)=><span key={j}>{a.ok?'\u2713':'!'} {a.name.replaceAll('_',' ')}</span>)}</div>:null}<p className="fine">Canonical event facts are checked against retrieved data; AI commentary is not verified. See the event cards and evidence below.</p></details>}{m.nearby&&<NearbyPlan data={m.nearby}/>}</article>)}</div>
      {busy&&<p role="status">Marquee is thinking and checking event tools…</p>}
      {error&&<p className="planner-notice" role="alert">{error}</p>}
      <form onSubmit={e=>{e.preventDefault();send();}}><label htmlFor="planner-message" className="eyebrow">YOUR NEXT NIGHT OUT</label><textarea id="planner-message" value={input} onChange={e=>setInput(e.target.value)} maxLength={2000} rows={3} placeholder="Two of us, Atlanta, this weekend. What’s on?" disabled={busy||!configured}/><div className="planner-footer"><button type="button" disabled={busy||!messages.length} onClick={()=>{setMessages([]);setReset(true);setError('');}}>New conversation</button><button className="accent" disabled={busy||!configured||!input.trim()}>{busy?'Working…':'Ask Marquee →'}</button></div></form>
      <p className="fine">Uses the search settings below unless you ask otherwise. Messages and event results are sent to the model provider. Conversation context lasts for this session; recent turns are retained. Prices and seat views are shown only when supplied.</p>
    </div></div>
  </section>;
}
