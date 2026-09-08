"""OpenAI-compatible local model adapter (Ollama, LM Studio, llama.cpp). Unreachable is a distinct state so a configured fallback can take over."""
import os
import time
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

    def _client(self, timeout):
        # Optional SOCKS proxy (Tailscale sidecar) applies only to local-model traffic.
        proxy = os.getenv('LOCAL_LLM_PROXY') or None
        return httpx.AsyncClient(timeout=timeout, proxy=proxy)

    async def available(self):
        if not self.configured():
            return False
        try:
            async with self._client(2) as client:
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
            # Tight connect timeout so a down server fails over fast; generation itself may be slow.
            async with self._client(httpx.Timeout(110, connect=3)) as client:
                response = await client.post(_base() + '/chat/completions', json=payload, headers=self._headers())
                response.raise_for_status()
                message = response.json()['choices'][0]['message']
        except httpx.TransportError as exc:
            raise LocalUnavailable(str(exc)) from None
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            # A reachable server that answers badly is a quality problem; do not mask it with the fallback.
            raise ChatError('The local model returned an invalid response. Fix or restart the local server, or switch the planner provider.') from None
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
    """Local first with cloud fallback on unavailability only; the user may pin either provider."""
    supports_preference = True

    def __init__(self, primary, backup):
        self.primary, self.backup = primary, backup
        self.last = None
        self._probe = (0.0, False)

    @property
    def label(self):
        return self.backup.label

    def configured(self):
        return self.primary.configured() or self.backup.configured()

    async def _up(self, max_age=30):
        now = time.monotonic()
        if now - self._probe[0] > max_age:
            self._probe = (now, await self.primary.available())
        return self._probe[1]

    async def status(self):
        up = await self._up(max_age=5)
        return {'model': self.last or (self.primary.label if up else self.backup.label),
                'providers': [
                    {'id': 'local', 'label': self.primary.label, 'configured': self.primary.configured(), 'available': up},
                    {'id': 'cloud', 'label': self.backup.label, 'configured': self.backup.configured(), 'available': self.backup.configured()}]}

    async def respond(self, items, instructions, tools, prefer='auto'):
        from .chat import ChatError
        if prefer == 'local':
            if not self.primary.configured():
                raise ChatError('No local model is configured on this server.')
            try:
                output = await self.primary.respond(items, instructions, tools)
            except LocalUnavailable:
                self._probe = (time.monotonic(), False)
                raise ChatError('The local model is unreachable. Start it, or switch the planner to auto or cloud.') from None
            self.last = self.primary.label
            return output
        if prefer != 'cloud' and self.primary.configured() and await self._up():
            try:
                output = await self.primary.respond(items, instructions, tools)
                self.last = self.primary.label
                return output
            except LocalUnavailable:
                self._probe = (time.monotonic(), False)
        if not self.backup.configured():
            raise ChatError('The local model is unreachable and no fallback model is configured.')
        output = await self.backup.respond(items, instructions, tools)
        self.last = self.backup.label
        return output
