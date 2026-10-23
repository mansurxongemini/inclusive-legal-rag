import json
import shutil
import subprocess
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import webhooks
from src.config import settings
from src.integrations.huquqplus_webhook import WebhookQueue, sign, verify_signature

SECRET = "s" * 40


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "HUQUQPLUS_WEBHOOK_SECRET", SECRET, raising=False)
    monkeypatch.setattr(webhooks, "_queue", WebhookQueue(str(tmp_path / "huquqplus.db")))
    app = FastAPI()
    app.include_router(webhooks.router)
    return TestClient(app)


def _event(**overrides):
    payload = {"event": "upsert", "event_id": "0b9f6f0e-1d1c-4c8e-9a51-1f2d3c4b5a69", "post_id": 2966,
               "lang": "uz", "modified_gmt": "2026-09-27 02:16:16", "site": "https://huquqplus.uz/"}
    payload.update(overrides)
    return payload


def _post(client, payload, secret=SECRET, ts=None, body=None):
    raw = body if body is not None else json.dumps(payload).encode()
    ts = str(int(time.time()) if ts is None else ts)
    return client.post("/api/v1/webhooks/huquqplus", content=raw, headers={
        "Content-Type": "application/json",
        "X-HuquqPlus-Timestamp": ts,
        "X-HuquqPlus-Signature": sign(secret, ts, raw),
    })


def test_valid_event_is_queued_once(client):
    r = _post(client, _event())
    assert r.status_code == 202 and r.json() == {"status": "queued"}
    # plugin retry with the same event_id is acknowledged but not queued twice
    assert _post(client, _event()).json() == {"status": "duplicate"}
    rows = webhooks._queue.pending()
    assert [(x["event"], x["post_id"], x["lang"]) for x in rows] == [("upsert", 2966, "uz")]


def test_delete_event_and_default_language(client):
    _post(client, _event(event="delete", event_id="aaaaaaaa-0000-0000-0000-000000000001", lang=""))
    row = webhooks._queue.pending()[0]
    assert row["event"] == "delete" and row["lang"] == "uz"


def test_ping_is_not_queued(client):
    r = _post(client, _event(event="ping", post_id=0))
    assert r.status_code == 202 and r.json() == {"status": "ok"}
    assert webhooks._queue.pending() == []


@pytest.mark.parametrize("case", ["wrong_secret", "stale", "future", "tampered"])
def test_bad_signatures_are_rejected(client, case):
    payload = _event()
    if case == "wrong_secret":
        r = _post(client, payload, secret="x" * 40)
    elif case == "stale":
        r = _post(client, payload, ts=int(time.time()) - 3600)
    elif case == "future":
        r = _post(client, payload, ts=int(time.time()) + 3600)
    else:
        ts = str(int(time.time()))
        raw = json.dumps(payload).encode()
        r = client.post("/api/v1/webhooks/huquqplus", content=raw.replace(b"2966", b"2967"), headers={
            "X-HuquqPlus-Timestamp": ts, "X-HuquqPlus-Signature": sign(SECRET, ts, raw)})
    assert r.status_code == 401
    assert webhooks._queue.pending() == []


def test_missing_headers_are_rejected(client):
    r = client.post("/api/v1/webhooks/huquqplus", json=_event())
    assert r.status_code == 401


def test_unconfigured_secret_disables_endpoint(client, monkeypatch):
    monkeypatch.setattr(settings, "HUQUQPLUS_WEBHOOK_SECRET", "", raising=False)
    assert _post(client, _event()).status_code == 503


def test_oversized_and_invalid_payloads(client):
    assert _post(client, None, body=b"{" + b" " * 9000 + b"}").status_code == 413
    assert _post(client, None, body=b"not json").status_code == 422
    assert _post(client, _event(event="drop_tables")).status_code == 422
    assert _post(client, _event(post_id=0)).status_code == 422
    assert _post(client, _event(event_id="../../etc")).status_code == 422


def test_failed_processing_is_retried_then_parked(tmp_path):
    q = WebhookQueue(str(tmp_path / "q.db"))
    q.enqueue("e1-aaaaaaaa", "upsert", 1, "uz")
    row_id = q.pending()[0]["id"]
    for _ in range(2):
        q.mark_failed(row_id, "network", max_attempts=3)
    assert q.pending()[0]["attempts"] == 2
    q.mark_failed(row_id, "network", max_attempts=3)
    assert q.pending() == [] and q.stats() == {"failed": 1}


def test_verify_signature_edge_cases():
    body = b"{}"
    ts = "1700000000"
    good = sign(SECRET, ts, body)
    assert verify_signature(SECRET, ts, body, good, now=1700000100)
    assert not verify_signature(SECRET, ts, body, good, now=1700000400)
    assert not verify_signature(SECRET, "abc", body, good, now=1700000000)
    assert not verify_signature("", ts, body, good, now=1700000000)
    assert not verify_signature(SECRET, ts, body, None, now=1700000000)


@pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")
def test_signature_matches_the_wordpress_plugin():
    """The plugin signs with PHP's hash_hmac over "<ts>.<body>"; both sides must agree byte for byte."""
    body = '{"event":"upsert","post_id":2966,"lang":"uz"}'
    ts = "1791791923"
    php = f"echo 'sha256=' . hash_hmac('sha256', '{ts}' . '.' . '{body}', '{SECRET}');"
    out = subprocess.run(["php", "-r", php], capture_output=True, text=True, timeout=30, check=True).stdout
    assert out == sign(SECRET, ts, body.encode())
