"""Short-TTL in-process caches for zone lookups and computed quotes.

Two things are worth not repeating on every cart render: the zone lookup (a
database round trip) and the rules pipeline (cheap, but free to skip). Both
are keyed on exactly what they depend on, so a hit is always the same answer
the miss would have produced.

Scope is one worker process. With several gunicorn workers an admin's rate
change reaches the others within TTL seconds - hence a TTL measured in
seconds, not minutes. Writes through the repository clear the local caches
immediately so the editing admin sees their own change at once.
"""

import threading
import time

DEFAULT_TTL_SECONDS = 60


class TTLCache:
    """A dict whose entries expire. Small, thread-safe, no dependencies."""

    def __init__(self, ttl_seconds=DEFAULT_TTL_SECONDS, max_entries=512):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._data = {}
        self._lock = threading.Lock()

    def get(self, key, default=None):
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default
            expires_at, value = entry
            if expires_at < now:
                self._data.pop(key, None)
                return default
            return value

    def set(self, key, value):
        now = time.monotonic()
        with self._lock:
            if len(self._data) >= self._max:
                # Cheapest possible eviction: drop everything already stale,
                # and if that frees nothing, drop the whole map. Both are
                # correct - the cache holds no state that isn't recomputable.
                self._data = {k: v for k, v in self._data.items() if v[0] >= now}
                if len(self._data) >= self._max:
                    self._data.clear()
            self._data[key] = (now + self._ttl, value)

    def clear(self):
        with self._lock:
            self._data.clear()


zone_cache = TTLCache()
quote_cache = TTLCache()
settings_cache = TTLCache(ttl_seconds=30)


def clear_all():
    """Called after any admin write to zones or delivery settings."""
    zone_cache.clear()
    quote_cache.clear()
    settings_cache.clear()
