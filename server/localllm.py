"""OpenAI-compatible local model adapter (Ollama, LM Studio, llama.cpp). Unreachable is a distinct state so a configured fallback can take over."""
import os
import httpx


class LocalUnavailable(Exception):
    pass


def _base():
    return os.getenv('LOCAL_LLM_BASE_URL', '').rstrip('/')


class LocalModel:
    @property
    def label(self):
        return 'Local \u00b7 ' + os.getenv('LOCAL_LLM_MODEL', '')

    def configured(self):
        return bool(_base() and os.getenv('LOCAL_LLM_MODEL'))

    def _headers(self):
        key = os.getenv('LOCAL_LLM_API_KEY')
        return {'Authorization': 'Bearer ' + key} if key else {}

    async def available(self):
        if not self.configured():
            return False
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(_base() + '/models', headers=self._headers())
                return response.status_code < 500
        except httpx.HTTPError:
            return False

    def _messages(self, items, instructions):
        messages = [{'role': 'system', 'content': instructions}]
        for item in items:
            kind = item.get('type')
            if kind == 'function_call':
                messages.append({'role': 'assistant', 'content': None,
                                 'tool_calls': [{'id': item.get('call_id', 'call_0'), 'type': 'function',
                                                 'function': {'name': item.get('name', ''), 'arguments': item.get('arguments', '{}')}}]})
            elif kind == 'function_call_output':
                messages.append({'role': 'tool', 'tool_call_id': item.get('call_id', ''), 'content': item.get('output', '')})
            elif kind == 'message' or ('role' in item and 'type' not in item):
                content = item.get('content')
                if isinstance(content, list):
                    content = ''.join(c.get('text', '') for c in content if isinstance(c, dict))
                if item.get('role') in ('user', 'assistant', 'system') and isinstance(content, str) and content:
                    messages.append({'role': item['role'], 'content': content})
            # Responses-only items (reasoning, refusals) are not replayable here and are skipped.
        return messages

    async def respond(self, items, instructions, tools):
        from .chat import ChatError
        if not self.configured():
            raise LocalUnavailable('Local model is not configured.')
        payload = {'model': os.environ['LOCAL_LLM_MODEL'],
                   'messages': self._messages(items, instructions),
                   'tools': [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'],
                                                               'parameters': t['parameters']}} for t in tools],
                   'max_tokens': 2200}
        try:
            async with httpx.AsyncClient(timeout=140) as client:
                response = await client.post(_base() + '/chat/completions', json=payload, headers=self._headers())
                response.raise_for_status()
                message = response.json()['choices'][0]['message']
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise LocalUnavailable(str(exc)) from None
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            # Any other local failure also yields to the fallback; the reply badge shows who answered.
            raise LocalUnavailable('Local model request failed.') from None
        output = []
        for i, call in enumerate(message.get('tool_calls') or []):
            function = call.get('function') or {}
            output.append({'type': 'function_call', 'call_id': call.get('id') or f'call_{i}',
                           'name': function.get('name', ''), 'arguments': function.get('arguments', '{}')})
        text = message.get('content')
        if isinstance(text, str) and text.strip():
            output.append({'type': 'message', 'role': 'assistant',
                           'content': [{'type': 'output_text', 'text': text}]})
        if not output:
            raise ChatError('The local model returned no usable reply. Please retry.')
        return output


class FallbackModel:
    """Try the local model first; hand the same conversation to the cloud model when local is unavailable."""

    def __init__(self, primary, backup):
        self.primary, self.backup = primary, backup
        self.last = None

    @property
    def label(self):
        return self.backup.label

    def configured(self):
        return self.primary.configured() or self.backup.configured()

    async def active(self):
        if await self.primary.available():
            return self.primary.label
        return self.backup.label

    async def respond(self, items, instructions, tools):
        from .chat import ChatError
        if self.primary.configured():
            try:
                output = await self.primary.respond(items, instructions, tools)
                self.last = self.primary.label
                return output
            except LocalUnavailable:
                pass
        if not self.backup.configured():
            raise ChatError('The local model is unreachable and no fallback model is configured.')
        output = await self.backup.respond(items, instructions, tools)
        self.last = self.backup.label
        return output
