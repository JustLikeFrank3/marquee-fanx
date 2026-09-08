import type {Tool,ToolCall} from './types';
type ModelContext={registerTool:(tool:Tool&{execute:(args:Record<string,unknown>)=>Promise<unknown>})=>void|Promise<void>;unregisterTool?:(name:string)=>void};
export async function registerBridge(context:ModelContext|undefined,tools:Tool[],call:ToolCall) {
  if(!context?.registerTool) return {count:0,cleanup:()=>{}};
  const registered:string[]=[];
  try {
    for(const tool of tools){await context.registerTool({...tool,execute:async args=>({content:[{type:'text',text:JSON.stringify(await call(tool.name,args))}]})});registered.push(tool.name);}
  } catch(e){registered.forEach(n=>context.unregisterTool?.(n));throw e;}
  return {count:registered.length,cleanup:()=>registered.forEach(n=>context.unregisterTool?.(n))};
}
export function browserContext():ModelContext|undefined {
  return (navigator as Navigator&{modelContext?:ModelContext}).modelContext ?? (document as Document&{modelContext?:ModelContext}).modelContext;
}
