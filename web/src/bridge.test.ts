import {describe,it,expect,vi} from 'vitest';
import {registerBridge} from './bridge';
describe('browser bridge',()=>{
  it('registers server definitions unchanged and forwards arguments',async()=>{
    const tools=[{name:'verify_plan',description:'Verify statements',inputSchema:{type:'object',additionalProperties:false}}];
    const registerTool=vi.fn(),unregisterTool=vi.fn(),call=vi.fn().mockResolvedValue({verdict:'FAIL'});
    const bridge=await registerBridge({registerTool,unregisterTool},tools,call);
    const {execute,...definition}=registerTool.mock.calls[0][0];
    expect(definition).toEqual(tools[0]);
    const args={text:'section 112',evidence_ids:['a']};await execute(args);
    expect(call).toHaveBeenCalledWith('verify_plan',args);expect(bridge.count).toBe(1);
    bridge.cleanup();expect(unregisterTool).toHaveBeenCalledWith('verify_plan');
  });
  it('does not advertise nonexistent browser support',async()=>{
    expect((await registerBridge(undefined,[],vi.fn())).count).toBe(0);
  });
  it('rolls back partial registration',async()=>{
    const registerTool=vi.fn().mockImplementationOnce(()=>{}).mockImplementationOnce(()=>{throw Error('unsupported');});
    const unregisterTool=vi.fn();
    await expect(registerBridge({registerTool,unregisterTool},[{name:'a',description:'a',inputSchema:{}},{name:'b',description:'b',inputSchema:{}}],vi.fn())).rejects.toThrow();
    expect(unregisterTool).toHaveBeenCalledWith('a');
  });
});
