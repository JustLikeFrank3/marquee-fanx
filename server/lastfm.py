"""Last.fm artist similarity adapter. An attributed recommendation signal, never a canonical concert fact."""
import asyncio
import os
import time
import httpx
from .data import now_iso
from .genres import canonical

SOURCE = 'Last.fm artist.getSimilar'


class SimilarSource:
    def __init__(self):
        self.cache = {}
        self.lock = asyncio.Lock()

    def configured(self):
        return bool(os.getenv('LASTFM_API_KEY'))

    async def _fetch(self, seed, limit):
        """Return similar-artist rows for one seed, [] for an unknown artist, None on failure."""
        return await self._call(seed, 'artist.getsimilar', limit)

    async def _fetch_tags(self, seed, limit):
        """Return top-tag rows for one seed, [] for an unknown artist, None on failure."""
        return await self._call(seed, 'artist.gettoptags', limit)

    async def _call(self, seed, method, limit):
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                for attempt in range(2):
                    response = await client.get('https://ws.audioscrobbler.com/2.0/',
                        params={'method': method, 'artist': seed, 'format': 'json',
                                'limit': limit, 'autocorrect': 1, 'api_key': os.environ['LASTFM_API_KEY']})
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == 0:
                            await asyncio.sleep(0.5)
                            continue
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get('error') == 6:  # unknown artist: a real empty answer, not an outage
                        return []
                    if 'error' in payload:
                        return None
                    if method == 'artist.gettoptags':
                        rows = (payload.get('toptags') or {}).get('tag') or []
                        found = []
                        for row in rows:
                            if not isinstance(row, dict):
                                continue
                            name = row.get('name')
                            count = row.get('count')
                            if not isinstance(name, str) or not name.strip():
                                continue
                            found.append({'name': name.strip(),
                                          'count': count if isinstance(count, int) and not isinstance(count, bool) else 0})
                        return found[:limit]
                    rows = (payload.get('similarartists') or {}).get('artist') or []
                    found = []
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        name = row.get('name')
                        if not isinstance(name, str) or not name.strip():
                            continue
                        try:
                            match = round(float(row.get('match')), 3)
                        except (TypeError, ValueError):
                            match = None
                        found.append({'name': name.strip(), 'match': match})
                    return found[:limit]
        except (httpx.HTTPError, ValueError):
            return None
        return None

    async def similar(self, seeds, per_seed=8):
        return await self._cached('similar', self._fetch, seeds, per_seed)

    async def top_tags(self, seeds, per_seed=10):
        return await self._cached('tags', self._fetch_tags, seeds, per_seed)

    async def _cached(self, kind, fetch, seeds, per_seed):
        fetched = now_iso()
        if not self.configured():
            return {'status': 'unconfigured', 'source': SOURCE, 'fetched_at': fetched, 'seeds': {},
                    'failed_seeds': list(seeds),
                    'note': 'Last.fm similarity is not configured on this server.'}
        results, failed = {}, []
        async with self.lock:
            now = time.monotonic()
            self.cache = {k: v for k, v in self.cache.items() if v[0] > now}
            for seed in list(seeds)[:10]:
                key = (kind, canonical(seed))
                if not key[1]:
                    continue
                if key in self.cache:
                    results[seed] = [dict(r) for r in self.cache[key][1]]
                    continue
                rows = await fetch(seed, per_seed)
                if rows is None:
                    failed.append(seed)
                    continue
                if len(self.cache) >= 50:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[key] = (now + 21600, rows)
                results[seed] = [dict(r) for r in rows]
        status = 'ok' if not failed else 'partial' if results else 'error'
        return {'status': status, 'source': SOURCE, 'fetched_at': fetched,
                'seeds': results, 'failed_seeds': failed}
