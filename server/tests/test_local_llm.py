import asyncio
import pytest
from server.localllm import LocalModel, FallbackModel, LocalUnavailable
from server.chat import ChatError

TOOLS = [{'name': 'search_events', 'description': 'd', 'parameters': {'type': 'object'}, 'strict': False}]

def test_items_translate_to_chat_messages(monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_BASE_URL', 'http://127.0.0.1:11434/v1')
    monkeypatch.setenv('LOCAL_LLM_MODEL', 'test-model')
    items = [{'role': 'user', 'content': 'hi'},
             {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'checking'}]},
             {'type': 'function_call', 'call_id': 'c1', 'name': 'search_events', 'arguments': '{}'},
             {'type': 'function_call_output', 'call_id': 'c1', 'output': '{"events":[]}'},
             {'type': 'reasoning', 'encrypted_content': 'opaque'}]
    messages = LocalModel()._messages(items, 'sys')
    assert messages[0] == {'role': 'system', 'content': 'sys'}
    assert messages[1] == {'role': 'user', 'content': 'hi'}
    assert messages[2] == {'role': 'assistant', 'content': 'checking'}
    assert messages[3]['tool_calls'][0]['function']['name'] == 'search_events'
    assert messages[4] == {'role': 'tool', 'tool_call_id': 'c1', 'content': '{"events":[]}'}
    assert len(messages) == 5  # reasoning items are not replayable

class FakeResponse:
    def __init__(self, payload, status=200): self.payload, self.status_code = payload, status
    def json(self): return self.payload
    def raise_for_status(self): pass

class FakeClient:
    def __init__(self, payload): self.payload = payload
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, json=None, headers=None): return FakeResponse(self.payload)
    async def get(self, url, headers=None): return FakeResponse(self.payload)

def test_chat_completion_maps_to_responses_output(monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_BASE_URL', 'http://127.0.0.1:11434/v1')
    monkeypatch.setenv('LOCAL_LLM_MODEL', 'test-model')
    payload = {'choices': [{'message': {'content': 'found it', 'tool_calls': [
        {'id': 'abc', 'type': 'function', 'function': {'name': 'search_events', 'arguments': '{"query":""}'}}]}}]}
    monkeypatch.setattr('server.localllm.httpx.AsyncClient', lambda **kw: FakeClient(payload))
    output = asyncio.run(LocalModel().respond([{'role': 'user', 'content': 'hi'}], 'sys', TOOLS))
    assert output[0] == {'type': 'function_call', 'call_id': 'abc', 'name': 'search_events', 'arguments': '{"query":""}'}
    assert output[1]['content'][0]['text'] == 'found it'

class StubModel:
    def __init__(self, label, output=None, unavailable=False, is_configured=True):
        self.label, self.output, self.unavailable, self.is_configured = label, output, unavailable, is_configured
    def configured(self): return self.is_configured
    async def available(self): return not self.unavailable and self.is_configured
    async def respond(self, items, instructions, tools):
        if self.unavailable: raise LocalUnavailable('down')
        return self.output

def test_fallback_prefers_local_and_records_label():
    model = FallbackModel(StubModel('Local · q', output=[{'type': 'message'}]), StubModel('Azure · a'))
    assert asyncio.run(model.respond([], 'i', [])) == [{'type': 'message'}]
    assert model.last == 'Local · q'
    assert asyncio.run(model.active()) == 'Local · q'

def test_fallback_switches_to_cloud_when_local_is_down():
    model = FallbackModel(StubModel('Local · q', unavailable=True), StubModel('Azure · a', output=[{'type': 'message'}]))
    assert asyncio.run(model.respond([], 'i', [])) == [{'type': 'message'}]
    assert model.last == 'Azure · a'
    assert asyncio.run(model.active()) == 'Azure · a'

def test_fallback_without_any_configured_model_fails_closed():
    model = FallbackModel(StubModel('Local · q', unavailable=True), StubModel('Azure · a', is_configured=False))
    with pytest.raises(ChatError):
        asyncio.run(model.respond([], 'i', []))

def test_unconfigured_local_is_unavailable(monkeypatch):
    monkeypatch.delenv('LOCAL_LLM_BASE_URL', raising=False)
    monkeypatch.delenv('LOCAL_LLM_MODEL', raising=False)
    local = LocalModel()
    assert not local.configured()
    assert not asyncio.run(local.available())
