"""HTTP hardening: security headers, public body limit, the caller's address behind a trusted proxy, the daily cap,
the closed-by-default administration of a deployment and the unpublished developer scripts."""
import json

import httpx
import pytest
from starlette.requests import Request

from src.api.app import app
from src.api.middleware.hardening import DailyBudget, client_ip
from src.config import settings


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def _request(peer="10.0.0.9", forwarded=None):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers, "method": "GET", "path": "/"})


@pytest.mark.asyncio
async def test_security_headers_on_pages_and_a_csp_that_keeps_the_docs_working():
    async with _client() as c:
        page = await c.get("/ask")
        docs = await c.get("/docs")
    assert page.headers["x-content-type-options"] == "nosniff" and page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert "microphone=(self)" in page.headers["permissions-policy"]
    assert "content-security-policy" not in docs.headers and docs.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_a_huge_public_request_is_rejected_before_it_is_read(monkeypatch):
    monkeypatch.setattr(settings, "MAX_PUBLIC_BODY_BYTES", 1000)
    async with _client() as c:
        big = await c.post("/api/v1/query", content=json.dumps({"question": "a" * 5000}),
                           headers={"content-type": "application/json"})
        small = await c.post("/api/v1/query", json={"question": ""})
    assert big.status_code == 413
    assert small.status_code in (400, 422)                          # reaches the route: validation, not the limit


@pytest.mark.asyncio
async def test_developer_scripts_are_not_served():
    async with _client() as c:
        res = await c.get("/static/scratch/test_modals.mjs")
        ok = await c.get("/static/css/main.css")
    assert res.status_code == 404 and ok.status_code == 200


def test_x_forwarded_for_is_trusted_only_for_configured_proxies(monkeypatch):
    spoofed = _request(forwarded="6.6.6.6, 203.0.113.7")
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", 0)
    assert client_ip(spoofed) == "10.0.0.9"                          # anyone can send the header
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", 1)
    assert client_ip(spoofed) == "203.0.113.7"                       # the address the proxy itself saw
    assert client_ip(_request()) == "10.0.0.9"


def test_daily_budget_counts_generations_and_resets_each_day(monkeypatch):
    budget = DailyBudget()
    assert [budget.consume(2) for _ in range(3)] == [True, True, False]
    assert budget.consume(0) is True                                 # 0 = no cap
    budget._day -= 1
    assert budget.consume(2) is True


def test_administration_is_closed_to_loopback_once_a_key_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOOPBACK_ENABLED", None)
    monkeypatch.setattr(settings, "ADMIN_API_KEY", None)
    assert settings.admin_loopback_enabled is True                   # a developer's machine
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "k" * 20)
    assert settings.admin_loopback_enabled is False                  # a deployment
    monkeypatch.setattr(settings, "ADMIN_LOOPBACK_ENABLED", True)
    assert settings.admin_loopback_enabled is True                   # explicit choice wins
