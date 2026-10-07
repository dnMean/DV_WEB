"""In-memory token bucket, keyed by (user_id, tool)."""
import threading
import time
from collections.abc import Callable, Hashable


class TokenBucketLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._buckets: dict[Hashable, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: Hashable, per_minute: int) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        rate = per_minute / 60.0
        with self._lock:
            now = self._clock()
            tokens, last = self._buckets.get(key, (float(per_minute), now))
            tokens = min(float(per_minute), tokens + (now - last) * rate)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return True, 0.0
            self._buckets[key] = (tokens, now)
            return False, (1 - tokens) / rate
