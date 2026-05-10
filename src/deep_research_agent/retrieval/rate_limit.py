"""Process-wide async token-bucket rate limiter.

All retrieval clients (Brave, Semantic Scholar, arXiv) share named
buckets registered here so every agent in the process competes for the
same budget. Default capacity=1 makes `acquire()` behave like a
min-interval spacer; raise capacity to allow bursts up to `capacity`
tokens after an idle stretch.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class TokenBucket:
    """Async token bucket.

    Refills at `rate` tokens/sec up to `capacity`. `acquire()` blocks
    under the lock until enough tokens are available, so callers are
    serialized through the bucket in FIFO order (asyncio.Lock is fair
    on CPython).
    """

    def __init__(self, rate: float, capacity: float | None = None, name: str = "") -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self._rate = rate
        self._capacity = float(capacity) if capacity is not None else 1.0
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._name = name

    def set_rate(self, rate: float, capacity: float | None = None) -> None:
        """Reconfigure the refill rate (and optionally capacity).

        Used when config loads after the bucket has been registered with
        a default. Token balance is clipped to the new capacity but
        otherwise untouched; the next acquire() recomputes against the
        new rate.
        """
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self._rate = rate
        if capacity is not None:
            self._capacity = float(capacity)
            if self._tokens > self._capacity:
                self._tokens = self._capacity

    async def acquire(self, tokens: float = 1.0) -> None:
        enter_at = time.monotonic()
        paced_s = 0.0
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._last_refill = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    break
                wait = (tokens - self._tokens) / self._rate
                paced_s += wait
                await asyncio.sleep(wait)
        total_s = time.monotonic() - enter_at
        queue_ms = int(max(0.0, total_s - paced_s) * 1000)
        pace_ms = int(paced_s * 1000)
        if queue_ms > 100 or pace_ms > 100:
            logger.info(
                "rate_limit name=%s queue_ms=%d pace_ms=%d rate=%.2f/s",
                self._name or "unnamed",
                queue_ms,
                pace_ms,
                self._rate,
            )


_BUCKETS: dict[str, TokenBucket] = {}


def get_bucket(name: str, rate: float, capacity: float | None = None) -> TokenBucket:
    """Return the process-wide bucket for `name`, creating it on first use.

    Subsequent calls ignore the rate/capacity args - use
    `bucket.set_rate(...)` to reconfigure an existing bucket.
    """
    bucket = _BUCKETS.get(name)
    if bucket is None:
        bucket = TokenBucket(rate=rate, capacity=capacity, name=name)
        _BUCKETS[name] = bucket
    return bucket
