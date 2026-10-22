"""
HTTP hardening that does not depend on the route: security headers, a body-size limit on the public endpoints,
the real client address behind a trusted proxy and a daily cap on generated answers.
"""
import time
from typing import Optional

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.config import settings

# Interactive docs load Swagger UI from a CDN; every other page is served by this app alone.
_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
_NO_CSP_PATHS = ("/docs", "/redoc", "/openapi.json")
PUBLIC_BODY_PREFIXES = (
    "/api/v1/query", "/api/v1/feedback", "/api/v1/inclusive/query", "/api/v1/assistant", "/api/v1/openai",
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {k.lower() for k, _ in headers}

                def add(name: bytes, value: str) -> None:
                    if name not in present:
                        headers.append((name, value.encode("latin-1")))

                add(b"x-content-type-options", "nosniff")
                add(b"x-frame-options", "DENY")
                add(b"referrer-policy", "same-origin")
                add(b"permissions-policy", "camera=(), geolocation=(), microphone=(self)")
                if not path.startswith(_NO_CSP_PATHS):
                    add(b"content-security-policy", _CSP)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodyLimitMiddleware:
    """413 for a public request body larger than MAX_PUBLIC_BODY_BYTES (declared or actually received)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = settings.MAX_PUBLIC_BODY_BYTES
        if (scope["type"] != "http" or limit <= 0 or scope.get("method") not in ("POST", "PUT", "PATCH")
                or not scope.get("path", "").startswith(PUBLIC_BODY_PREFIXES)):
            await self.app(scope, receive, send)
            return

        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            await self._too_large(send)
            return

        received = 0
        too_large = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        started = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if too_large and not started:
                started = True
                await self._too_large(send)
                return
            if too_large:
                return
            started = started or message["type"] == "http.response.start"
            await send(message)

        await self.app(scope, limited_receive, guarded_send)

    @staticmethod
    async def _too_large(send: Send) -> None:
        body = b'{"detail":"So\'rov hajmi juda katta."}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def client_ip(request: Request) -> str:
    """
    Address of the caller. Behind TRUSTED_PROXIES reverse proxies the rightmost X-Forwarded-For entries were added
    by those proxies, so the caller is the entry TRUSTED_PROXIES from the right; with no trusted proxy the header is
    ignored (anyone can send it) and the TCP peer is used.
    """
    peer = request.client.host if request.client else "127.0.0.1"
    hops = settings.TRUSTED_PROXIES
    if hops <= 0:
        return peer
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    return forwarded[-hops] if len(forwarded) >= hops else peer


class DailyBudget:
    """Counts the answers generated today; `consume()` returns False once PUBLIC_DAILY_GENERATIONS is used up."""

    def __init__(self) -> None:
        self._day: Optional[int] = None
        self._used = 0

    def consume(self, limit: Optional[int] = None) -> bool:
        limit = settings.PUBLIC_DAILY_GENERATIONS if limit is None else limit
        if limit <= 0:
            return True
        today = int(time.time() // 86400)
        if today != self._day:
            self._day, self._used = today, 0
        if self._used >= limit:
            return False
        self._used += 1
        return True


generation_budget = DailyBudget()
