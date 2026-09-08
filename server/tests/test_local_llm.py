import asyncio
import httpx
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
    @property
    def text(self): return str(self.payload)
    def json(self): return self.payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError('err', request=None, response=None)

class FakeClient:
    def __init__(self, payload, status=200, connect_error=False): self.payload, self.status, self.connect_error = payload, status, connect_error
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, json=None, headers=None):
        if self.connect_error: raise httpx.ConnectError('down')
        return FakeResponse(self.payload, self.status)
    async def get(self, url, headers=None): return FakeResponse(self.payload, self.status)

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
    def __init__(self, label, output=None, unavailable=False, is_configured=True, quality_error=False):
        self.label, self.output, self.unavailable, self.is_configured, self.quality_error = label, output, unavailable, is_configured, quality_error
    def configured(self): return self.is_configured
    async def available(self): return not self.unavailable and self.is_configured
    async def respond(self, items, instructions, tools):
        if self.unavailable: raise LocalUnavailable('down')
        if self.quality_error: raise ChatError('bad output')
        return self.output

def test_fallback_prefers_local_and_records_label():
    model = FallbackModel(StubModel('Local · q', output=[{'type': 'message'}]), StubModel('Azure · a'))
    assert asyncio.run(model.respond([], 'i', [])) == [{'type': 'message'}]
    assert model.last == 'Local · q'
    status = asyncio.run(model.status())
    assert status['model'] == 'Local · q'
    assert status['providers'][0]['available'] is True

def test_fallback_switches_to_cloud_when_local_is_down():
    model = FallbackModel(StubModel('Local · q', unavailable=True), StubModel('Azure · a', output=[{'type': 'message'}]))
    assert asyncio.run(model.respond([], 'i', [])) == [{'type': 'message'}]
    assert model.last == 'Azure · a'
    assert asyncio.run(model.status())['providers'][0]['available'] is False

def test_local_quality_errors_are_not_masked_by_fallback():
    model = FallbackModel(StubModel('Local · q', quality_error=True), StubModel('Azure · a', output=[{'type': 'message'}]))
    with pytest.raises(ChatError, match='bad output'):
        asyncio.run(model.respond([], 'i', []))

def test_pinned_cloud_skips_available_local():
    model = FallbackModel(StubModel('Local · q', output=[{'type': 'message', 'who': 'local'}]),
                          StubModel('Azure · a', output=[{'type': 'message', 'who': 'cloud'}]))
    assert asyncio.run(model.respond([], 'i', [], prefer='cloud'))[0]['who'] == 'cloud'
    assert model.last == 'Azure · a'

def test_pinned_local_fails_honestly_when_down():
    model = FallbackModel(StubModel('Local · q', unavailable=True), StubModel('Azure · a', output=[{'type': 'message'}]))
    with pytest.raises(ChatError, match='unreachable'):
        asyncio.run(model.respond([], 'i', [], prefer='local'))

def test_fallback_without_any_configured_model_fails_closed():
    model = FallbackModel(StubModel('Local · q', unavailable=True), StubModel('Azure · a', is_configured=False))
    with pytest.raises(ChatError):
        asyncio.run(model.respond([], 'i', []))

def test_http_error_is_quality_not_unavailability(monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_BASE_URL', 'http://127.0.0.1:11434/v1')
    monkeypatch.setenv('LOCAL_LLM_MODEL', 'test-model')
    monkeypatch.setattr('server.localllm.httpx.AsyncClient', lambda **kw: FakeClient({}, status=500))
    with pytest.raises(ChatError):
        asyncio.run(LocalModel().respond([{'role': 'user', 'content': 'hi'}], 'sys', TOOLS))
    monkeypatch.setattr('server.localllm.httpx.AsyncClient', lambda **kw: FakeClient({}, connect_error=True))
    with pytest.raises(LocalUnavailable):
        asyncio.run(LocalModel().respond([{'role': 'user', 'content': 'hi'}], 'sys', TOOLS))

def test_unconfigured_local_is_unavailable(monkeypatch):
    monkeypatch.delenv('LOCAL_LLM_BASE_URL', raising=False)
    monkeypatch.delenv('LOCAL_LLM_MODEL', raising=False)
    local = LocalModel()
    assert not local.configured()
    assert not asyncio.run(local.available())
