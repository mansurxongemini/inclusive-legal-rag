import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request

from src.api.auth.admin import is_admin_request
from src.api.middleware.hardening import client_ip
from src.config import settings


class SlidingWindowLimiter:
    """
    Per-key sliding-window rate limiter, in memory (one API process), shared by the public endpoints (key = caller's
    address or API key) and the assistant API (key = client / end user). Sync endpoints run in a thread pool, so the
    state is guarded by a lock.
    """

    _SWEEP_EVERY = 500  # calls between sweeps of idle keys

    def __init__(self, window_s: float = 60.0, default_limit: int = 60):
        self.window = window_s
        self.default_limit = default_limit
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._calls = 0
        self._lock = threading.Lock()

    def hit(self, key: str, limit: Optional[int] = None, now: Optional[float] = None) -> Optional[int]:
        """Records a hit; returns None when allowed, else the seconds until a slot frees up. An explicit limit of 0
        blocks everything (it is a limit, not "use the default")."""
        limit = self.default_limit if limit is None else limit
        now = time.monotonic() if now is None else now
        with self._lock:
            self._calls += 1
            if self._calls % self._SWEEP_EVERY == 0:      # idle keys must not grow the dict without bound
                for k in [k for k, q in self._hits.items() if not q or now - q[-1] >= self.window]:
                    del self._hits[k]
            q = self._hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if limit <= 0 or len(q) >= limit:
                return max(1, int(self.window - (now - q[0])) + 1) if q else int(self.window)
            q.append(now)
            return None

    def check(self, request: Request, key: Optional[str] = None, limit: Optional[int] = None, scope: Optional[str] = None) -> None:
        """Raises 429 (with Retry-After) once the caller exceeded the limit. The caller is the explicit key, else the
        client address, optionally in its own `scope` so that e.g. browsing does not use up the question budget."""
        ident = key or (f"{scope}:{client_ip(request)}" if scope else client_ip(request))
        retry = self.hit(ident, limit)
        if retry is not None:
            raise HTTPException(
                status_code=429,
                detail="So'rovlar soni me'yordan oshib ketdi. Iltimos, birozdan so'ng qayta urinib ko'ring (Rate limit exceeded).",
                headers={"Retry-After": str(retry)},
            )

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = SlidingWindowLimiter(default_limit=settings.RATE_LIMIT_PER_MINUTE)


def limit_public_browsing(request: Request) -> None:
    """The public norm / document / article reads have their own per-address budget; the administrator's dashboard,
    which reads the same endpoints while it is used, is not limited."""
    if not is_admin_request(request):
        rate_limiter.check(request, scope="browse", limit=settings.PUBLIC_BROWSE_RATE_PER_MINUTE)
