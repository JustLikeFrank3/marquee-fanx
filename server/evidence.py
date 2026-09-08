import copy
import secrets
import time
from datetime import datetime, timezone

class EvidenceError(Exception):
    pass

class EvidenceStore:
    def __init__(self):
        self.sessions = {}

    def create(self):
        now = time.monotonic()
        self.sessions = {k:v for k,v in self.sessions.items() if v['expires'] > now}
        if len(self.sessions) >= 500:
            raise EvidenceError('Demo session capacity reached. Try again later.')
        token = secrets.token_urlsafe(32)
        self.sessions[token] = {'expires':now+3600, 'items':{}}
        return token

    def session(self, token):
        value = self.sessions.get(token)
        if not value or value['expires'] <= time.monotonic():
            self.sessions.pop(token, None)
            raise EvidenceError('Session expired. Refresh the page to start a new session.')
        return value

    def add(self, token, event, raw, party_size=2):
        session = self.session(token)
        items = session['items']
        now = time.monotonic()
        items = {k:v for k,v in items.items() if v['expires'] > now}
        session['items'] = items
        if len(items) >= 100:
            items.pop(next(iter(items)))
        age = max(0, (datetime.now(timezone.utc)-datetime.fromisoformat(event['fetched_at'])).total_seconds())
        handle = secrets.token_urlsafe(18)
        items[handle] = {'event':copy.deepcopy(event), 'raw':copy.deepcopy(raw), 'party_size':party_size,
                         'expires':now+max(0,600-age)}
        return handle

    def get(self, token, handles):
        items = self.session(token)['items']
        result = []
        for handle in dict.fromkeys(handles):
            item = items.get(handle)
            if not item or item['expires'] <= time.monotonic():
                items.pop(handle, None)
                raise EvidenceError('Evidence missing or expired. Search or plan again before verifying.')
            result.append(item)
        return result
