from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class MemoryRateLimiter:
    """Small single-instance limiter for sensitive endpoints on the first deployment."""

    def __init__(self, maximum: int, window_seconds: int) -> None:
        self.maximum = maximum
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def consume(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            attempts = self._attempts[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.maximum:
                retry_after = max(1, int(self.window_seconds - (now - attempts[0])))
                return False, retry_after
            attempts.append(now)
            return True, 0

    async def reset(self, key: str) -> None:
        async with self._lock:
            self._attempts.pop(key, None)
