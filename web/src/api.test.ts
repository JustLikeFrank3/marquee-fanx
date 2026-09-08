import {it,expect,vi,afterEach} from 'vitest';
afterEach(()=>{vi.unstubAllGlobals();vi.resetModules();});
it('renews a lost server session and retries the search once',async()=>{
  const fetch=vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({session_id:'old',mode:'live'})))
    .mockResolvedValueOnce(new Response(JSON.stringify({error:'Session expired.'}),{status:401}))
    .mockResolvedValueOnce(new Response(JSON.stringify({session_id:'new',mode:'live'})))
    .mockResolvedValueOnce(new Response(JSON.stringify({events:[{event_id:1}]})));
  vi.stubGlobal('fetch',fetch);
  const {call}=await import('./api');
  expect(await call('search_events',{query:'eastern'})).toEqual({events:[{event_id:1}]});
  expect(fetch.mock.calls[3][1].headers['X-Marquee-Session']).toBe('new');
  expect(fetch).toHaveBeenCalledTimes(4);
});
