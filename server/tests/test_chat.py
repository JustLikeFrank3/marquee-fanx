import asyncio
import copy
import json
from datetime import date,timedelta
from unittest.mock import AsyncMock
import pytest
from server.chat import ChatService,ChatInput,ChatError,ResponsesModel
from server.data import EventSource,sample_records,now_iso
from server.evidence import EvidenceStore
from server.tools import ToolService

def request(message='Find concerts',reset=False):
    return ChatInput(message=message,reset=reset,context={'date_from':date.today(),'date_to':date.today()+timedelta(days=30)})

def answer(text='Here are the events returned by the search.'):
    return [{'type':'message','role':'assistant','content':[{'type':'output_text','text':text}]}]

def tool(name='plan_night',args=None):
    return [{'type':'function_call','call_id':'call_1','name':name,
             'arguments':json.dumps(args if args is not None else request().context.model_dump(mode='json'))}]

class FakeModel:
    def __init__(self,outputs): self.outputs=iter(outputs);self.inputs=[]
    def configured(self): return True
    async def respond(self,items,instructions,tools):
        self.inputs.append(copy.deepcopy(items))
        return next(self.outputs)

def setup(outputs):
    store=EvidenceStore();source=EventSource('sample')
    records=sample_records()
    for record in records: record['stats']={}
    source.search=AsyncMock(return_value=(records,now_iso()))
    model=FakeModel(outputs)
    return ChatService(ToolService(source,store),store,model),store,model

def test_real_tools_supply_cards_and_verified_unknown_prices():
    chat,store,model=setup([tool(),answer()])
    result=asyncio.run(chat.send(request(),store.create()))
    assert result['report']['verdict']=='PASS'
    assert result['results']['events']
    assert all(e['lowest_price'] is None for e in result['results']['events'])
    assert model.inputs[1][-1]['type']=='function_call_output'
    assert result['actions']==[{'name':'plan_night','ok':True},{'name':'verify_plan','ok':True,'automatic':True}]
    assert json.loads(model.inputs[1][-1]['output'])['canonical_fact_report']['verdict']=='PASS'

def test_followup_isolation_and_reset():
    async def exercise():
        chat,store,model=setup([answer('first'),answer('followup'),answer('other'),answer('reset')])
        one,two=store.create(),store.create()
        await chat.send(request('my private preference'),one)
        await chat.send(request('refine that'),one)
        assert 'my private preference' in json.dumps(model.inputs[-1])
        await chat.send(request('different visitor'),two)
        assert 'my private preference' not in json.dumps(model.inputs[-1])
        await chat.send(request('start again',True),one)
        assert 'my private preference' not in json.dumps(model.inputs[-1])
    asyncio.run(exercise())

def test_unknown_tool_is_not_executed_and_failure_is_visible():
    chat,store,model=setup([tool('send_email',{}),answer('I cannot do that.')])
    result=asyncio.run(chat.send(request(),store.create()))
    assert result['actions']==[{'name':'unknown','ok':False}]
    assert result['report'] is None and result['results'] is None
    assert 'error' in model.inputs[-1][-1]['output']

def test_loop_bound_and_failed_turn_not_committed():
    chat,store,model=setup([tool()]*5)
    token=store.create()
    with pytest.raises(ChatError,match='search limit'): asyncio.run(chat.send(request(),token))
    assert not store.session(token).get('chat_turns')
    assert store.session(token)['chat_busy'] is False

def test_busy_session_and_global_cap():
    chat,store,model=setup([answer()]);token=store.create()
    store.session(token)['chat_busy']=True
    with pytest.raises(ChatError,match='already'): asyncio.run(chat.send(request(),token))
    store.session(token)['chat_busy']=False
    import time
    chat.calls.extend([time.monotonic()]*60)
    with pytest.raises(ChatError,match='hourly limit'): asyncio.run(chat.send(request(),token))
    assert not model.inputs

def test_missing_config_is_explicit(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    chat,store,_=setup([]);chat.model=ResponsesModel()
    with pytest.raises(ChatError,match='model connection'): asyncio.run(chat.send(request(),store.create()))

def test_chat_route_validates_and_reports_unconfigured(monkeypatch):
    from fastapi.testclient import TestClient
    from server.app import app
    from server.app import chat as app_chat
    monkeypatch.setattr(app_chat,'model',ResponsesModel())
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with TestClient(app,base_url='http://127.0.0.1:8000') as client:
        token=client.post('/api/session').json()['session_id']
        status=client.get('/api/chat/status').json()
        assert status['configured'] is False
        assert status['model'].startswith('OpenAI')
        headers={'X-Marquee-Session':token}
        assert client.post('/api/chat/message',json=request().model_dump(mode='json'),headers=headers).status_code==503
        assert client.post('/api/chat/message',json={'message':'hi'},headers=headers).status_code==422
