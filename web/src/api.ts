let session = '';
let pending: Promise<{mode:'sample'|'live'}>|null = null;
export async function startSession():Promise<{mode:'sample'|'live'}> {
  if (!pending) pending = fetch('/api/session',{method:'POST'}).then(async r=>{const v=await r.json();if(!r.ok)throw Error(v.error||'Unable to start session');session=v.session_id;return v;}).catch(e=>{pending=null;throw e;});
  return pending;
}
export async function call<T>(name:string,args:unknown):Promise<T> {
  const response=await sessionFetch('/api/'+name,args);
  const value=await response.json(); if(!response.ok)throw Error(value.error||'Unable to load events. Please try again.'); return value;
}
export async function rpc(method:string,params:unknown={}) {
  const r=await sessionFetch('/mcp',{jsonrpc:'2.0',id:crypto.randomUUID(),method,params});
  const v=await r.json();if(!r.ok||v.error)throw Error(v.error?.message||'Agent service unavailable');return v.result;
}

async function sessionFetch(url:string,body:unknown):Promise<Response> {
  for(let attempt=0;attempt<2;attempt++){
    await startSession();
    const usedSession=session;
    const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json, text/event-stream','X-Marquee-Session':usedSession},body:JSON.stringify(body)});
    if(response.status!==401||attempt===1)return response;
    if(session===usedSession){session='';pending=null;}
  }
  throw Error('Unable to renew session. Refresh the page.');
}
