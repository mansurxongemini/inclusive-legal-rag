import time
from collections import defaultdict
from typing import Dict, List, Optional
from fastapi import Request, HTTPException
from src.config import settings
from src.api.middleware.hardening import client_ip


class TokenBucketRateLimiter:
    """Sliding-window in-memory rate limiter per IP address (or explicit key) with zero external daemon."""

    _SWEEP_EVERY = 500  # calls between sweeps of idle buckets

    def __init__(self, requests_per_minute: int = 60):
        self.limit = requests_per_minute
        self.window = 60.0  # seconds
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self._calls = 0

    def _sweep(self, now: float) -> None:
        """Drops buckets with no activity inside the window so the dict cannot grow without bound."""
        stale = [k for k, ts in self.requests.items() if not ts or now - ts[-1] >= self.window]
        for k in stale:
            del self.requests[k]

    def check(self, request: Request, key: Optional[str] = None, limit: Optional[int] = None):
        ident = key or client_ip(request)
        max_requests = limit or self.limit
        now = time.time()

        self._calls += 1
        if self._calls % self._SWEEP_EVERY == 0:
            self._sweep(now)

        # Clean timestamps older than window
        timestamps = [t for t in self.requests[ident] if now - t < self.window]
        self.requests[ident] = timestamps

        if len(timestamps) >= max_requests:
            raise HTTPException(
                status_code=429,
                detail="So'rovlar soni me'yordan oshib ketdi. Iltimos, birozdan so'ng qayta urinib ko'ring (Rate limit exceeded)."
            )

        self.requests[ident].append(now)


rate_limiter = TokenBucketRateLimiter(settings.RATE_LIMIT_PER_MINUTE)
