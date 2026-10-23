import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from src.api.app import app
from src.ingestion.lex_client import LexClient
from src.ingestion.lex_structured import LexDocument, LexUnit


def _dummy_doc(doc_id: str, status: str = "active") -> LexDocument:
    return LexDocument(
        doc_id=doc_id,
        url=f"https://lex.uz/docs/{doc_id}",
        number="O'RQ-999",
        title="Nogironligi bo'lgan shaxslar huquqlari to'g'risida",
        doc_type="Qonun",
        adopted_date="2024-05-15",
        effective_date="2024-05-16",
        status=status,
        units=[
            LexUnit(
                kind="article",
                number="1",
                title="Qonunning maqsadi",
                text="Ushbu Qonunning maqsadi nogironligi bo'lgan shaxslar huquqlarini himoya qilishdan iborat.",
            )
        ],
    )


@pytest.fixture
def mock_lex_client(monkeypatch):
    class MockLex:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def fetch_document(self, doc_id):
            return f"<html><body>Mock document {doc_id}</body></html>"

        def fetch_url(self, url):
            return "<html><body>Mock url</body></html>"

    monkeypatch.setattr("src.api.routes.corpus_admin.LexClient", MockLex)
    monkeypatch.setattr("scripts.build_disability_corpus.LexClient", MockLex)

    from src.ingestion.lex_structured import LexDocumentParser

    def mock_parse(self, html, doc_id):
        return _dummy_doc(doc_id)

    monkeypatch.setattr(LexDocumentParser, "parse", mock_parse)


@pytest.mark.asyncio
async def test_corpus_preview_validation_errors():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Invalid sources -> 422
        bad_sources = [
            "not_an_id",
            "12",  # less than 3 digits
            "https://evil.com/docs/-12345",
            "http://lex.uz/docs/-12345",  # not https
            "https://lex.uz/other/-12345",
            "",
        ]
        for src in bad_sources:
            res = await ac.post("/api/v1/admin/corpus/preview", json={"source": src})
            assert res.status_code == 422, f"Expected 422 for source: {src}"


@pytest.mark.asyncio
async def test_corpus_preview_success(mock_lex_client):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Valid ID
        res = await ac.post("/api/v1/admin/corpus/preview", json={"source": "-999"})
        assert res.status_code == 200
        data = res.json()
        assert data["lex_id"] == "-999"
        assert data["number"] == "O'RQ-999"
        assert "nogironligi bo'lgan" in data["title"].lower()
        assert data["doc_type"] == "Qonun"
        assert data["units"] == 1
        assert "in_registry" in data
        assert "include" in data

        # Valid URL
        res_url = await ac.post("/api/v1/admin/corpus/preview", json={"source": "https://lex.uz/docs/-999"})
        assert res_url.status_code == 200
        assert res_url.json()["lex_id"] == "-999"

        # Valid www.lex.uz URL
        res_www = await ac.post("/api/v1/admin/corpus/preview", json={"source": "https://www.lex.uz/docs/-999"})
        assert res_www.status_code == 200
        assert res_www.json()["lex_id"] == "-999"


@pytest.mark.asyncio
async def test_corpus_add_and_refresh_flow(monkeypatch):
    from src.api.routes import corpus_admin

    class MockProcess:
        def __init__(self):
            self.returncode = 0

        async def communicate(self):
            stdout = b"refresh: 1 docs, 1 changed/new indexed, 0 removed -> /tmp/report.json"
            stderr = b""
            return stdout, stderr

    mock_proc = MockProcess()

    async def mock_exec(*args, **kwargs):
        return mock_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_exec)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Add job
        res_add = await ac.post("/api/v1/admin/corpus/add", json={"lex_id": "-999", "include": "all"})
        assert res_add.status_code == 200
        job_id = res_add.json()["job_id"]

        # Wait briefly for background task
        await asyncio.sleep(0.05)

        # Check job status
        res_job = await ac.get(f"/api/v1/admin/corpus/jobs/{job_id}")
        assert res_job.status_code == 200
        job_data = res_job.json()
        assert job_data["status"] == "done"
        assert "1 changed/new indexed" in (job_data["summary"] or "")

        # Refresh job: only for an act that is in the registry
        from src.api.routes import corpus_admin
        monkeypatch.setattr(corpus_admin, "_registry_entry", lambda lex_id: None)
        res_unknown = await ac.post("/api/v1/admin/corpus/refresh", json={"lex_id": "-999"})
        assert res_unknown.status_code == 404
        monkeypatch.setattr(corpus_admin, "_registry_entry", lambda lex_id: {"lex_id": lex_id, "include": "all"})
        res_ref = await ac.post("/api/v1/admin/corpus/refresh", json={"lex_id": "-999"})
        assert res_ref.status_code == 200
        job_id2 = res_ref.json()["job_id"]

        await asyncio.sleep(0.05)
        res_job2 = await ac.get(f"/api/v1/admin/corpus/jobs/{job_id2}")
        assert res_job2.status_code == 200
        assert res_job2.json()["status"] == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("returncode", [0, 1])
async def test_corpus_job_clears_server_article_cache(monkeypatch, returncode):
    """The job runs scripts/build_disability_corpus.py in a subprocess, so the server's in-memory article cache is
    outdated afterwards - on success and also on failure (the script may have written part of the corpus)."""
    from src.api.app import get_store
    from src.api.routes import corpus_admin

    class MockProcess:
        def __init__(self):
            self.returncode = returncode

        async def communicate(self):
            return b"refresh: 1 docs, 1 changed/new indexed, 0 removed", b"boom" if returncode else b""

    async def mock_exec(*args, **kwargs):
        return MockProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_exec)
    monkeypatch.setattr(corpus_admin, "_registry_entry", lambda lex_id: {"lex_id": lex_id, "include": "all"})

    fts = get_store().fts_store
    fts.get_article("synthetic_law_art_15")          # may be absent; the sentinel below is what matters
    fts._article_cache["__stale_sentinel__"] = object()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/v1/admin/corpus/refresh", json={"lex_id": "-999"})
        assert res.status_code == 200
        await asyncio.sleep(0.05)
        job = (await ac.get(f"/api/v1/admin/corpus/jobs/{res.json()['job_id']}")).json()
        assert job["status"] == ("done" if returncode == 0 else "failed")

    assert "__stale_sentinel__" not in fts._article_cache


@pytest.mark.asyncio
async def test_corpus_job_conflict_409(monkeypatch):
    from src.api.routes import corpus_admin

    # Mock a long running subprocess
    class SlowProcess:
        def __init__(self):
            self.returncode = 0

        async def communicate(self):
            await asyncio.sleep(1.0)
            return b"refresh: 1 docs, 0 changed/new indexed, 0 removed", b""

    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **kw: SlowProcess())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res1 = await ac.post("/api/v1/admin/corpus/add", json={"lex_id": "-888"})
        assert res1.status_code == 200

        # Immediate second request while first is still running -> 409
        res2 = await ac.post("/api/v1/admin/corpus/add", json={"lex_id": "-888"})
        assert res2.status_code == 409
        assert "bajarilmoqda" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_corpus_admin_requires_admin():
    transport = ASGITransport(app=app)
    # Using remote client headers (X-Forwarded-For) without Authorization to test require_admin rejection (401)
    headers = {"X-Forwarded-For": "203.0.113.195"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        res_preview = await ac.post("/api/v1/admin/corpus/preview", json={"source": "-999"})
        assert res_preview.status_code == 401

        res_add = await ac.post("/api/v1/admin/corpus/add", json={"lex_id": "-999"})
        assert res_add.status_code == 401

        res_refresh = await ac.post("/api/v1/admin/corpus/refresh", json={"lex_id": "-999"})
        assert res_refresh.status_code == 401

    # Remote client with invalid token -> 403
    bad_auth_headers = {"X-Forwarded-For": "203.0.113.195", "X-Admin-Key": "wrong-key"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=bad_auth_headers) as ac:
        res_bad = await ac.post("/api/v1/admin/corpus/preview", json={"source": "-999"})
        assert res_bad.status_code == 403


def test_build_disability_corpus_add_command(tmp_path, mock_lex_client):
    from scripts.build_disability_corpus import cmd_add
    import argparse

    reg_file = tmp_path / "disability_registry.json"
    reg_file.write_text(json.dumps({"documents": []}, ensure_ascii=False), encoding="utf-8")

    # 1. Add new document
    args = argparse.Namespace(
        lex_id="-999",
        include="all",
        registry_file=str(reg_file),
        delay=0.0,
    )
    cmd_add(args)

    data = json.loads(reg_file.read_text(encoding="utf-8"))
    assert len(data["documents"]) == 1
    doc = data["documents"][0]
    assert doc["lex_id"] == "-999"
    assert doc["source"] == "admin"
    assert doc["tier"] == 2
    assert doc["include"] == "all"
    assert doc["number"] == "O'RQ-999"

    # 2. Add same document with include update
    args_update = argparse.Namespace(
        lex_id="-999",
        include="disability_articles",
        registry_file=str(reg_file),
        delay=0.0,
    )
    cmd_add(args_update)

    data2 = json.loads(reg_file.read_text(encoding="utf-8"))
    assert len(data2["documents"]) == 1
    assert data2["documents"][0]["include"] == "disability_articles"


def test_build_disability_corpus_add_repealed_fails(tmp_path, monkeypatch):
    from scripts.build_disability_corpus import cmd_add
    import argparse
    from src.ingestion.lex_structured import LexDocumentParser

    class MockLex:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def fetch_document(self, doc_id):
            return "<html><body>Repealed</body></html>"

        def fetch_url(self, url):
            return "<html><body>Repealed</body></html>"

    monkeypatch.setattr("scripts.build_disability_corpus.LexClient", MockLex)

    def mock_parse(self, html, doc_id):
        return _dummy_doc(doc_id, status="repealed")

    monkeypatch.setattr(LexDocumentParser, "parse", mock_parse)

    reg_file = tmp_path / "disability_registry.json"
    reg_file.write_text(json.dumps({"documents": []}), encoding="utf-8")

    args = argparse.Namespace(
        lex_id="-999",
        include="all",
        registry_file=str(reg_file),
        delay=0.0,
    )
    with pytest.raises(SystemExit) as exc:
        cmd_add(args)
    assert "faol emas" in str(exc.value)


def test_lex_id_accepts_only_ascii_digits():
    from fastapi import HTTPException
    from src.api.routes.corpus_admin import _valid_lex_id, parse_source_to_id

    assert parse_source_to_id("https://lex.uz/uz/docs/-5049511#-5054422") == "-5049511"
    assert parse_source_to_id("-5049511") == "-5049511"
    for bad in ("١٢٣٤", "-12²34", "https://lex.uz.evil.com/docs/-5049511", "http://lex.uz/docs/-5049511", "12; rm -rf /"):
        with pytest.raises(HTTPException):
            parse_source_to_id(bad)
    with pytest.raises(HTTPException):
        _valid_lex_id("-12²34")


def test_amending_title_detection():
    from src.api.routes.corpus_admin import _AMENDING_TITLE

    assert _AMENDING_TITLE.search("Hukumatining ayrim qarorlariga oʻzgartirish va qoʻshimchalar kiritish toʻgʻrisida")
    assert _AMENDING_TITLE.search("Ayrim qarorlarini oʻz kuchini yoʻqotgan deb topish toʻgʻrisida")
    assert not _AMENDING_TITLE.search("Nogironligi boʻlgan shaxslarning huquqlari toʻgʻrisida")
