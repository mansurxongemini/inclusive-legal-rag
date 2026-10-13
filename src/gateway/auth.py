"""
Authentication and limits of the assistant API.

- The key travels only in `Authorization: Bearer <key>` or `X-API-Key` (never in the URL, where it would end up
  in proxy logs and browser history).
- A server (secret) key is refused when the request carries an `Origin` header: such a key must never be shipped to
  a browser. A browser (publishable) key works only from the exact origins configured for its client.
- Limits: requests per minute per client, per end user (`user_ref`; per IP for browser keys) and a daily quota.
  Every refusal names its reason in `{"code", "message"}` and a 429 carries `Retry-After`.

Behind a reverse proxy, run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy ip>` so that the client IP
is the real one.
"""
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

from fastapi import Depends, HTTPException, Request

from src.gateway.clients import KIND_BROWSER, Client, get_client_store, normalize_origin


@dataclass
class ClientContext:
    client: Client
    key_id: str
    origin: Optional[str]
    ip: str


def gateway_error(status: int, code: str, message: str, headers: Optional[Dict[str, str]] = None) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message}, headers=headers)


class SlidingWindowLimiter:
    """Per-key sliding one-minute window, in memory (one API process)."""

    _SWEEP_EVERY = 1000

    def __init__(self, window_s: float = 60.0):
        self.window = window_s
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._calls = 0

    def hit(self, key: str, limit: int, now: Optional[float] = None) -> Optional[int]:
        """Records a hit; returns None when allowed, else the seconds until a slot frees up."""
        now = time.monotonic() if now is None else now
        self._calls += 1
        if self._calls % self._SWEEP_EVERY == 0:
            for k in [k for k, q in self._hits.items() if not q or now - q[-1] >= self.window]:
                del self._hits[k]
        q = self._hits[key]
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= limit:
            return max(1, int(self.window - (now - q[0])) + 1)
        q.append(now)
        return None

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindowLimiter()


def _too_many(retry_after: int, code: str, message: str) -> HTTPException:
    return gateway_error(429, code, message, headers={"Retry-After": str(retry_after)})


def _extract_key(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization") or ""
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    key = request.headers.get("x-api-key")
    return key.strip() if key else None


async def authenticate_client(request: Request) -> ClientContext:
    raw = _extract_key(request)
    if not raw:
        raise gateway_error(401, "missing_api_key",
                            "API kaliti kerak: 'Authorization: Bearer <kalit>' sarlavhasini yuboring.",
                            headers={"WWW-Authenticate": "Bearer"})
    store = get_client_store()
    found = store.resolve_key(raw)
    if found is None:
        # unknown, revoked, expired and disabled keys look the same to the caller
        raise gateway_error(401, "invalid_api_key", "API kaliti yaroqsiz yoki bekor qilingan.",
                            headers={"WWW-Authenticate": "Bearer"})
    client, key = found

    origin_header = request.headers.get("origin")
    origin: Optional[str] = None
    if origin_header:
        try:
            origin = normalize_origin(origin_header)
        except ValueError:
            origin = None
    if client.kind == KIND_BROWSER:
        if not origin or origin not in client.allowed_origins:
            store.record_rejected(client.client_id)
            raise gateway_error(403, "origin_not_allowed", "Bu kalit ushbu saytdan foydalanish uchun ruxsat etilmagan.")
    elif origin_header:
        store.record_rejected(client.client_id)
        raise gateway_error(403, "secret_key_in_browser",
                            "Maxfiy (server) kaliti brauzerda ishlatilmaydi. Saytlar uchun brauzer kalitini oling "
                            "yoki so'rovni o'z serveringiz orqali yuboring. Bu kalitni almashtirish tavsiya etiladi.")

    ip = request.client.host if request.client else "unknown"
    retry = limiter.hit(f"client:{client.client_id}", client.rate_per_min)
    if retry is not None:
        store.record_rejected(client.client_id)
        raise _too_many(retry, "rate_limited", "Daqiqalik so'rovlar limiti tugadi. Birozdan so'ng qayta urining.")
    if client.kind == KIND_BROWSER:
        retry = limiter.hit(f"client:{client.client_id}:ip:{ip}", client.user_rate_per_min)
        if retry is not None:
            store.record_rejected(client.client_id)
            raise _too_many(retry, "user_rate_limited", "Juda ko'p savol yuborildi. Birozdan so'ng qayta urining.")
    return ClientContext(client=client, key_id=key.key_id, origin=origin, ip=ip)


def require_scope(scope: str):
    async def _dep(ctx: ClientContext = Depends(authenticate_client)) -> ClientContext:
        if scope not in ctx.client.scopes:
            raise gateway_error(403, "insufficient_scope", f"Bu kalitga '{scope}' amaliga ruxsat berilmagan.")
        return ctx
    return _dep


def enforce_user_limit(ctx: ClientContext, user_ref: Optional[str]) -> None:
    """Per-end-user limit of a server client (a browser client is already limited per IP)."""
    if not user_ref or ctx.client.kind == KIND_BROWSER:
        return
    retry = limiter.hit(f"client:{ctx.client.client_id}:user:{user_ref}", ctx.client.user_rate_per_min)
    if retry is not None:
        get_client_store().record_rejected(ctx.client.client_id)
        raise _too_many(retry, "user_rate_limited", "Juda ko'p savol yuborildi. Birozdan so'ng qayta urining.")


def enforce_daily_quota(ctx: ClientContext) -> None:
    """Counts the request against today's quota; call it once per accepted question, after validation."""
    if not get_client_store().take_daily_request(ctx.client):
        raise _too_many(3600, "quota_exceeded", "Bugungi so'rovlar kvotasi tugadi.")
