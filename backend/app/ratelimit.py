"""Simple in-memory sliding-window rate limiter.

LIMITATION: per-process memory. With several workers/containers use a gateway/WAF or Redis-backed limiter.
"""
import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window: int = 60) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
