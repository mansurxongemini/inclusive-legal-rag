"""Assistant API security core: keys, origins, scopes, limits, pseudonymous user ids."""
import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.gateway import auth, clients
from src.gateway.auth import ClientContext, enforce_daily_quota, enforce_user_limit, require_scope
from src.gateway.clients import ClientStore, normalize_origin, user_ref


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = ClientStore(str(tmp_path / "integrations.db"))
    monkeypatch.setattr(clients, "_store", s)
    monkeypatch.setattr(clients, "_hash_secret_cache", b"test-secret")
    auth.limiter.reset()
    yield s
    auth.limiter.reset()


@pytest.fixture
def api(store):
    app = FastAPI()

    @app.post("/ask")
    async def ask(ctx: ClientContext = Depends(require_scope("ask"))):
        enforce_user_limit(ctx, user_ref(ctx.client.client_id, "tg:42"))
        enforce_daily_quota(ctx)
        return {"client": ctx.client.client_id}

    @app.post("/feedback")
    async def feedback(ctx: ClientContext = Depends(require_scope("feedback"))):
        return {"ok": True}

    return TestClient(app)


def _bearer(key):
    return {"Authorization": f"Bearer {key}"}


def test_server_key_works_and_only_its_hash_is_stored(store, api):
    c = store.create_client("Huquq+ bot")
    raw, info = store.issue_key(c.client_id)
    assert raw.startswith("hpk_live_") and raw not in info.prefix
    assert api.post("/ask", headers=_bearer(raw)).json() == {"client": c.client_id}
    assert api.post("/ask", headers={"X-API-Key": raw}).status_code == 200
    with store._conn() as conn:
        dump = "\n".join(str(r) for r in conn.execute("SELECT * FROM client_keys"))
    assert raw not in dump


def test_missing_unknown_revoked_expired_and_disabled_keys_are_refused(store, api):
    assert api.post("/ask").json()["detail"]["code"] == "missing_api_key"
    assert api.post("/ask", headers=_bearer("hpk_live_nope")).json()["detail"]["code"] == "invalid_api_key"
    c = store.create_client("bot")
    raw, info = store.issue_key(c.client_id)
    store.revoke_key(info.key_id)
    assert api.post("/ask", headers=_bearer(raw)).status_code == 401

    raw2, info2 = store.issue_key(c.client_id, expires_at=time.time() + 60)
    assert api.post("/ask", headers=_bearer(raw2)).status_code == 200
    with store._conn() as conn:
        conn.execute("UPDATE client_keys SET expires_at = ? WHERE key_id = ?", (time.time() - 1, info2.key_id))
    assert api.post("/ask", headers=_bearer(raw2)).status_code == 401

    raw3, _ = store.issue_key(c.client_id)
    store.update_client(c.client_id, is_active=False)
    assert api.post("/ask", headers=_bearer(raw3)).status_code == 401


def test_key_in_query_string_is_ignored(store, api):
    c = store.create_client("bot")
    raw, _ = store.issue_key(c.client_id)
    assert api.post(f"/ask?api_key={raw}").status_code == 401
    assert api.post(f"/ask?token={raw}").status_code == 401


def test_secret_key_is_refused_from_a_browser(store, api):
    c = store.create_client("bot")
    raw, _ = store.issue_key(c.client_id)
    r = api.post("/ask", headers={**_bearer(raw), "Origin": "https://huquqplus.uz"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "secret_key_in_browser"


def test_browser_key_only_from_allowed_origins(store, api):
    c = store.create_client("sayt vidjeti", kind="browser", allowed_origins=["https://HuquqPlus.uz/"])
    raw, _ = store.issue_key(c.client_id)
    assert raw.startswith("hpk_pub_")
    assert api.post("/ask", headers={**_bearer(raw), "Origin": "https://huquqplus.uz"}).status_code == 200
    for bad in ({}, {"Origin": "https://evil.example"}, {"Origin": "https://huquqplus.uz.evil.example"},
                {"Origin": "http://huquqplus.uz"}):
        r = api.post("/ask", headers={**_bearer(raw), **bad})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "origin_not_allowed", bad


def test_scopes_are_enforced(store, api):
    c = store.create_client("faqat savol", scopes=["ask"])
    raw, _ = store.issue_key(c.client_id)
    assert api.post("/ask", headers=_bearer(raw)).status_code == 200
    r = api.post("/feedback", headers=_bearer(raw))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "insufficient_scope"


def test_rate_limits_answer_429_with_retry_after(store, api):
    c = store.create_client("bot", rate_per_min=2, user_rate_per_min=100)
    raw, _ = store.issue_key(c.client_id)
    assert [api.post("/ask", headers=_bearer(raw)).status_code for _ in range(3)] == [200, 200, 429]
    r = api.post("/ask", headers=_bearer(raw))
    assert r.json()["detail"]["code"] == "rate_limited" and int(r.headers["Retry-After"]) >= 1


def test_per_user_limit_and_daily_quota(store, api):
    c = store.create_client("bot", user_rate_per_min=1)
    raw, _ = store.issue_key(c.client_id)
    assert api.post("/ask", headers=_bearer(raw)).status_code == 200
    r = api.post("/ask", headers=_bearer(raw))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "user_rate_limited"

    auth.limiter.reset()
    q = store.create_client("kvota", daily_quota=1, user_rate_per_min=100)
    raw_q, _ = store.issue_key(q.client_id)
    assert api.post("/ask", headers=_bearer(raw_q)).status_code == 200
    r = api.post("/ask", headers=_bearer(raw_q))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "quota_exceeded"
    assert store.usage(q.client_id)[0]["requests"] == 1 and store.usage(q.client_id)[0]["rejected"] == 1


def test_publishable_key_cannot_unlock_a_server_client(store):
    c = store.create_client("bot")
    raw, _ = store.issue_key(c.client_id)
    forged = "hpk_pub_" + raw[len("hpk_live_"):]
    assert store.resolve_key(forged) is None


def test_validation_of_client_settings(store):
    with pytest.raises(ValueError):
        store.create_client("x", kind="browser")                                  # no origin
    with pytest.raises(ValueError):
        store.create_client("x", allowed_origins=["https://a.uz"])                # server key with origins
    with pytest.raises(ValueError):
        store.create_client("x", scopes=["admin"])
    with pytest.raises(ValueError):
        store.create_client("x", kind="browser", allowed_origins=["http://huquqplus.uz"])   # no plain http
    assert normalize_origin("http://localhost:5173/") == "http://localhost:5173"
    assert normalize_origin("https://huquqplus.uz:443") == "https://huquqplus.uz"
    with pytest.raises(ValueError):
        normalize_origin("https://huquqplus.uz/path")


def test_user_ref_is_stable_pseudonymous_and_per_client(store):
    a = user_ref("cli_a", "123456789")
    assert a == user_ref("cli_a", "123456789") and a.startswith("u_") and "123456789" not in a
    assert a != user_ref("cli_b", "123456789")
    assert user_ref("cli_a", "") is None and user_ref("cli_a", None) is None


def test_admin_endpoints_require_admin_and_show_key_once(store, monkeypatch):
    from src.gateway.admin_router import router
    app = FastAPI()
    app.include_router(router)
    local = TestClient(app)                                   # TestClient host counts as a direct loopback call
    r = local.post("/api/v1/admin/integrations/clients", json={"name": "Huquq+ bot"})
    assert r.status_code == 201
    raw, cid = r.json()["api_key"], r.json()["client"]["client_id"]
    detail = local.get(f"/api/v1/admin/integrations/clients/{cid}").json()
    assert raw not in str(detail) and detail["keys"][0]["is_usable"]

    remote = TestClient(app, base_url="http://testserver")
    monkeypatch.setattr("src.api.auth.admin.is_direct_loopback", lambda request: False)
    assert remote.get("/api/v1/admin/integrations/clients").status_code == 401
