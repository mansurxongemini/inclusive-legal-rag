"""
Administrative access control.

Every route that mutates the legal corpus, manages API keys or reads user data must depend on
`require_admin`. Access is granted when:

* the caller presents the configured `ADMIN_API_KEY` (``X-Admin-Key`` header or ``Authorization: Bearer``), or
* the request is a *direct* loopback connection (local dashboard). A request that carries proxy headers
  is treated as remote even if the proxy itself runs on localhost.

Everything else is rejected, so a deployment without `ADMIN_API_KEY` is closed to remote administration.
"""
import hmac
from typing import Optional

from fastapi import Header, HTTPException, Request

from src.config import settings

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded", "x-forwarded-host")


def is_direct_loopback(request: Request) -> bool:
    """True only for a connection that originates on this machine and did not pass through a proxy."""
    host = request.client.host if request.client else ""
    if host not in _LOOPBACK_HOSTS:
        return False
    return not any(h in request.headers for h in _PROXY_HEADERS)


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
    if is_direct_loopback(request):
        return

    if token:
        raise HTTPException(status_code=403, detail="Administrator kaliti noto'g'ri.")
    raise HTTPException(
        status_code=401,
        detail="Administrator huquqi talab qilinadi. X-Admin-Key sarlavhasi orqali ADMIN_API_KEY ni yuboring.",
    )
