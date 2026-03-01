"""Simple in-memory cache with TTL for read-heavy API endpoints."""
import time
from typing import Any, Callable


class TTLCache:
    """Thread-safe TTL cache for single values."""

    def __init__(self, ttl_seconds: float = 2.0):
        self._ttl = ttl_seconds
        self._value: Any = None
        self._timestamp: float = 0.0

    def get_or_compute(self, compute_fn: Callable[[], Any]) -> Any:
        now = time.monotonic()
        if now - self._timestamp < self._ttl and self._value is not None:
            return self._value
        self._value = compute_fn()
        self._timestamp = now
        return self._value

    def invalidate(self):
        self._timestamp = 0.0
        self._value = None
