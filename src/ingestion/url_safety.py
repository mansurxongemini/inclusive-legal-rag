"""
Outbound-URL validation for the ingestion endpoints (SSRF protection).

* `is_lex_uz_url` - strict host check (``"lex.uz" in netloc`` accepted ``lex.uz.evil.com``).
* `assert_public_http_url` - for "any legal website" ingestion: only http(s) to publicly routable addresses.
"""
import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

_LEX_HOST = "lex.uz"


def lex_uz_host_ok(hostname: Optional[str]) -> bool:
    host = (hostname or "").lower().rstrip(".")
    return host == _LEX_HOST or host.endswith("." + _LEX_HOST)


def is_lex_uz_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and lex_uz_host_ok(parsed.hostname)


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return addr.is_global and not addr.is_multicast


def assert_public_http_url(url: str) -> None:
    """Raises ValueError unless `url` is http(s) and every address its host resolves to is public."""
    try:
        parsed = urlparse(url.strip())
    except ValueError as e:
        raise ValueError(f"Yaroqsiz havola: {e}")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Faqat http/https havolalari qabul qilinadi.")

    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError(f"Domen aniqlanmadi: {host}")

    if not infos or not all(_is_public_ip(info[4][0]) for info in infos):
        raise ValueError("Ichki yoki xususiy tarmoq manzillariga so'rov yuborish taqiqlangan.")


async def httpx_public_request_hook(request) -> None:
    """httpx `request` event hook: validates the initial URL and every redirect hop."""
    assert_public_http_url(str(request.url))
