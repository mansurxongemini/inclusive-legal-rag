"""
Administrative access control.

Every route that mutates the legal corpus, manages API keys or reads user data must depend on
`require_admin`. Access is granted when:

* the caller presents the configured `ADMIN_API_KEY` (``X-Admin-Key`` header or ``Authorization: Bearer``), or
* the request is a *direct* loopback connection (local dashboard). A request that carries proxy headers
  is treated as remote even if the proxy itself runs on localhost. A loopback request that looks like it was
  steered by a web page (foreign `Host` = DNS rebinding, foreign `Origin` / `Sec-Fetch-Site: cross-site` =
  another site driving the visitor's browser) is treated as remote too.

Everything else is rejected, so a deployment without `ADMIN_API_KEY` is closed to remote administration.

A reverse proxy that forwards no `X-Forwarded-For` / `X-Real-IP` makes every remote caller look like a direct
loopback connection and cannot be told apart by the checks above: behind such a proxy set
`ADMIN_LOOPBACK_ENABLED=false`, which makes the key the only way in.
"""
import hmac
from typing import Optional
from urllib.parse import urlparse

from fastapi import Header, HTTPException, Request

from src.config import settings

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded", "x-forwarded-host")
# names a local client puts in the Host header ("test"/"testserver": the in-process test clients)
_LOOPBACK_HOST_NAMES = {"localhost", "127.0.0.1", "::1", "testserver", "test"}


def _host_name(host_header: str) -> str:
    """Hostname of a Host header value: 'localhost:8000' -> 'localhost', '[::1]:8000' -> '::1'."""
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def _is_web_page_driven(request: Request) -> bool:
    """True when the request was sent by a browser on behalf of a page that is not the dashboard itself."""
    if _host_name(request.headers.get("host", "")) not in _LOOPBACK_HOST_NAMES:
        return True                                    # DNS rebinding: a foreign name pointing at 127.0.0.1
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        return True
    origin = request.headers.get("origin")
    if origin is not None:
        # the dashboard is served by this app, so its own calls carry an Origin equal to the Host
        return urlparse(origin).netloc.lower() != request.headers.get("host", "").strip().lower()
    return False


def is_direct_loopback(request: Request) -> bool:
    """True only for a connection that originates on this machine, did not pass through a proxy and was not
    triggered by another web page."""
    host = request.client.host if request.client else ""
    if host not in _LOOPBACK_HOSTS:
        return False
    if any(h in request.headers for h in _PROXY_HEADERS):
        return False
    return not _is_web_page_driven(request)


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def require_admin(
    request: Request,
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
    authorization: Optional[str] = Header(None),
) -> None:
    token = x_admin_key or _bearer_token(authorization)
    configured = settings.ADMIN_API_KEY

    if configured and token and hmac.compare_digest(token.encode("utf-8"), configured.encode("utf-8")):
        return
    if settings.ADMIN_LOOPBACK_ENABLED and is_direct_loopback(request):
        return

    if token:
        raise HTTPException(status_code=403, detail="Administrator kaliti noto'g'ri.")
    raise HTTPException(
        status_code=401,
        detail="Administrator huquqi talab qilinadi. X-Admin-Key sarlavhasi orqali ADMIN_API_KEY ni yuboring.",
    )
