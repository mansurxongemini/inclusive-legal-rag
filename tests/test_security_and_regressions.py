"""
Regression tests for the issues found in the project review:
access control, SSRF, citation validation, retrieval correctness, cache and storage consistency.
"""
import json
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app, get_cache, get_store
from src.clients.openrouter import OpenRouterClient
from src.config import settings
from src.generation.generator import AnswerGenerator, GeneratedAnswer
from src.generation.validator import CitationValidator
from src.ingestion.url_safety import assert_public_http_url, is_lex_uz_url
from src.nlp.query_analyzer import QueryAnalyzer
from src.nlp.query_decomposer import LegalQueryDecomposer
from src.nlp.transliteration import cyrillic_to_latin
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.reranker import RetrievedArticleContext
from src.schema.canonical import CanonicalArticle
from src.storage.hybrid_store import HybridStore
from src.storage.vector_store import LanceVectorStore

PILOT = Path("data/pilot_laws/law_disability_2020.json")
REMOTE = ("203.0.113.7", 51000)


def _pilot_articles():
    with open(PILOT, "r", encoding="utf-8") as f:
        return [CanonicalArticle.model_validate(item) for item in json.load(f)]


@pytest.fixture(autouse=True)
async def seeded_store():
    store = get_store()
    if store.count() == 0:
        await store.seed_from_file(str(PILOT), client=OpenRouterClient())
    return store


def remote_client():
    return AsyncClient(transport=ASGITransport(app=app, client=REMOTE), base_url="http://api.example")


def local_client():
    return AsyncClient(transport=ASGITransport(app=app, client=("127.0.0.1", 40000)), base_url="http://localhost")


# ----------------------------------------------------------------------------------------------------------
# Access control
# ----------------------------------------------------------------------------------------------------------

ADMIN_CALLS = [
    ("get", "/api/v1/inclusive/admin/api-keys", None),
    ("post", "/api/v1/inclusive/admin/api-keys", {"name": "x"}),
    ("delete", "/api/v1/inclusive/admin/api-keys/key_abc", None),
    ("put", "/api/v1/inclusive/norms/law_disability_2020_art_15", {"text_uz": "tampered"}),
    ("post", "/api/v1/inclusive/admin/upload-json", []),
    ("post", "/api/v1/inclusive/admin/import-folder", None),
    ("post", "/api/v1/inclusive/admin/import-url", {"url": "https://lex.uz/uz/docs/-1"}),
    ("delete", "/api/v1/admin/article/law_disability_2020_art_15", None),
    ("put", "/api/v1/admin/article/law_disability_2020_art_15",
     {"title_uz": "t", "text_uz": "tampered", "revectorize": False}),
    ("get", "/api/v1/admin/stats", None),
    ("get", "/api/v1/feedback", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", ADMIN_CALLS)
async def test_admin_routes_reject_remote_callers(method, path, body):
    async with remote_client() as c:
        res = await c.request(method.upper(), path, json=body)
    assert res.status_code == 401, f"{method.upper()} {path} -> {res.status_code}"
    # nothing was modified
    assert get_store().get_article("law_disability_2020_art_15").get_text("uz") != "tampered"


@pytest.mark.asyncio
async def test_forged_referer_does_not_grant_access():
    async with remote_client() as c:
        res = await c.post(
            "/api/v1/inclusive/query",
            json={"question": "Nogironlik nafaqasi qanday tayinlanadi?"},
            headers={"Referer": "http://attacker.example:8000/"},
        )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_proxy_headers_disable_loopback_trust():
    # nginx on the same host shows up as 127.0.0.1 but always forwards the real client address
    async with local_client() as c:
        res = await c.get("/api/v1/inclusive/admin/api-keys", headers={"X-Forwarded-For": "198.51.100.9"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_direct_loopback_keeps_dashboard_working():
    async with local_client() as c:
        res = await c.get("/api/v1/inclusive/admin/api-keys")
    assert res.status_code == 200
    assert "api_keys" in res.json()


@pytest.mark.asyncio
async def test_admin_key_grants_remote_access(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "s3cret-admin-key")
    async with remote_client() as c:
        ok = await c.get("/api/v1/inclusive/admin/api-keys", headers={"X-Admin-Key": "s3cret-admin-key"})
        bearer = await c.get("/api/v1/feedback", headers={"Authorization": "Bearer s3cret-admin-key"})
        wrong = await c.get("/api/v1/inclusive/admin/api-keys", headers={"X-Admin-Key": "nope"})
    assert ok.status_code == 200
    assert bearer.status_code == 200
    assert wrong.status_code == 403


@pytest.mark.asyncio
async def test_valid_api_key_works_remotely_and_is_rate_limited_per_key():
    from src.api.auth.api_keys import api_key_manager
    created = api_key_manager.create_key("pytest-bot", rate_limit=2)
    headers = {"X-API-Key": created["api_key"]}
    body = {"question": "Nogironligi bo'lgan shaxslarga tibbiy yordam qanday ko'rsatiladi?", "language": "uz"}
    async with remote_client() as c:
        codes = [(await c.post("/api/v1/inclusive/query", json=body, headers=headers)).status_code for _ in range(3)]
    assert codes[:2] == [200, 200]
    assert codes[2] == 429


@pytest.mark.asyncio
async def test_import_folder_is_confined_to_data_directory():
    async with local_client() as c:
        for bad in ("/etc", "../..", "data/../..", "/home"):
            res = await c.post("/api/v1/inclusive/admin/import-folder", params={"directory_path": bad})
            assert res.status_code == 400, bad
        ok = await c.post("/api/v1/inclusive/admin/import-folder", params={"directory_path": "data/qonunlar"})
        assert ok.status_code == 200


@pytest.mark.asyncio
async def test_question_length_is_bounded():
    async with local_client() as c:
        res = await c.post("/api/v1/query", json={"question": "a" * 5000})
        assert res.status_code == 422
        res = await c.post("/api/v1/query", json={"question": "   "})
        assert res.status_code in (400, 422)


@pytest.mark.asyncio
async def test_norm_search_limit_cannot_be_negative():
    async with local_client() as c:
        res = await c.get("/api/v1/inclusive/norms", params={"limit": -1})
    assert res.status_code == 422


# ----------------------------------------------------------------------------------------------------------
# SSRF
# ----------------------------------------------------------------------------------------------------------

def test_lex_uz_host_check_is_strict():
    assert is_lex_uz_url("https://lex.uz/uz/docs/-5501227")
    assert is_lex_uz_url("https://www.lex.uz/docs/1")
    assert not is_lex_uz_url("https://lex.uz.evil.example/docs/1")
    assert not is_lex_uz_url("https://evil.example/?u=lex.uz")
    assert not is_lex_uz_url("https://evil.example/lex.uz/docs/1")
    assert not is_lex_uz_url("ftp://lex.uz/docs/1")
    assert not is_lex_uz_url("file:///etc/passwd")


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/admin",
    "http://localhost/",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/",
    "http://[::1]/",
    "file:///etc/passwd",
    "gopher://example.com/",
])
def test_internal_and_non_http_urls_are_blocked(url):
    with pytest.raises(ValueError):
        assert_public_http_url(url)


@pytest.mark.asyncio
async def test_import_url_rejects_lookalike_host():
    async with local_client() as c:
        res = await c.post("/api/v1/inclusive/admin/import-url", json={"url": "https://lex.uz.evil.example/uz/docs/-1"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_preview_url_blocks_internal_targets():
    async with local_client() as c:
        res = await c.post("/api/v1/admin/preview-url", json={"url": "http://169.254.169.254/latest/meta-data/"})
    assert res.status_code == 400


# ----------------------------------------------------------------------------------------------------------
# Citation validation
# ----------------------------------------------------------------------------------------------------------

def _ctx(index=2):
    return RetrievedArticleContext(article=_pilot_articles()[index], final_score=1.0, source_tag="primary")


def test_substantive_cited_answer_mentioning_topilmadi_is_not_a_refusal():
    ctx = _ctx()
    cid = ctx.article.canonical_id
    answer = (
        f"Nogironligi bo'lgan shaxslarga tibbiy yordam bepul ko'rsatiladi [{cid}]. "
        "Dori-darmon bo'yicha alohida muddat topilmadi, ammo umumiy tartib belgilangan. "
        + "Batafsil tartib normada ko'rsatilgan. " * 15
    )
    res = CitationValidator.validate_and_sanitize(answer, [ctx], "uz")
    assert not res.is_refusal
    assert [c.canonical_id for c in res.resolved_citations] == [cid]
    assert res.is_valid


def test_short_not_found_answer_is_still_a_refusal():
    res = CitationValidator.validate_and_sanitize("Ushbu savol bo'yicha ma'lumot topilmadi.", [_ctx()], "uz")
    assert res.is_refusal and res.resolved_citations == []


def test_uncited_answer_is_not_reported_as_verified():
    ctx = _ctx()
    res = CitationValidator.validate_and_sanitize(
        "Bu javob hech qanday normaga tayanmaydi va umumiy mulohazalardan iborat. " * 4, [ctx], "uz"
    )
    assert res.is_valid is False
    assert any("no_explicit_citation" in w for w in res.warnings)


def test_hallucinated_citation_fails_validation_and_is_not_shown():
    ctx = _ctx()
    cid = ctx.article.canonical_id
    res = CitationValidator.validate_and_sanitize(
        f"Huquq bor [{cid}]. Qo'shimcha imtiyoz ham mavjud [law_disability_2020_art_999].", [ctx], "uz"
    )
    assert res.is_valid is False
    assert "law_disability_2020_art_999" not in res.clean_answer
    assert "999" not in res.clean_answer


def test_plain_bracketed_words_are_not_counted_as_unresolved_citations():
    ctx = _ctx()
    cid = ctx.article.canonical_id
    res = CitationValidator.validate_and_sanitize(f"Tibbiy yordam bepul [{cid}]. [Muhim] [1]", [ctx], "uz")
    assert res.unresolved_citations == []
    assert res.is_valid


# ----------------------------------------------------------------------------------------------------------
# NLP
# ----------------------------------------------------------------------------------------------------------

def test_transliteration_preserves_line_breaks():
    out = cyrillic_to_latin("1. Салом дунё\n2. Нафақа қандай\n\n3. Муддат")
    assert out.count("\n") == 3
    assert out.startswith("1. Salom dunyo\n2.")


def test_numbered_questions_in_cyrillic_are_still_decomposed():
    q = (
        "Ногиронлик пенсияси учун ҳужжатлар\n"
        "1. Қайси идорага мурожаат қилинади ва қандай муддатда ариза берилади?\n"
        "2. Ариза рад этилса нима қилиш керак бўлади ва шикоят қаерга берилади?"
    )
    analysis = QueryAnalyzer.analyze(q)
    assert "\n" in analysis.normalized_query
    subs = LegalQueryDecomposer.decompose(analysis.normalized_query)
    assert [s.aspect_tag for s in subs[:2]] == ["case_q1", "case_q2"]


def test_uzbek_cyrillic_without_special_letters_is_not_russian():
    assert QueryAnalyzer.detect_language("Нафака олиш учун нима килиш керак") == "uz"
    assert QueryAnalyzer.detect_language("Какие льготы положены инвалиду для работы?") == "ru"
    assert QueryAnalyzer.detect_language("What benefits does a disabled person get?") == "en"


def test_short_disability_stems_need_a_word_start():
    types = QueryAnalyzer.extract_disability_types("Shartnomada ko'zda tutilgan imtiyozlar va karta olish tartibi")
    assert types == ["general"]
    assert "hearing" in QueryAnalyzer.extract_disability_types("Kar va eshitishda nuqsoni bor shaxslar")


# ----------------------------------------------------------------------------------------------------------
# Retrieval and storage
# ----------------------------------------------------------------------------------------------------------

async def _store_with_articles(tmp_path, numbers):
    store = HybridStore(str(tmp_path / "store"))
    base = _pilot_articles()[0]
    for n in numbers:
        art = base.model_copy(deep=True)
        art.canonical_id = f"test_code_art_{n}"
        art.metadata.law_id = "test_code"
        art.metadata.article_number = f"{n}-modda"
        await store.index_article(art, client=OpenRouterClient())
    return store


@pytest.mark.asyncio
async def test_direct_article_lookup_requires_an_exact_number(tmp_path):
    store = await _store_with_articles(tmp_path, ["15", "25"])
    # make the canonical-id fast path miss so the article_number fallback is exercised
    with store.fts_store._get_connection() as conn:
        conn.execute("UPDATE articles_metadata SET canonical_id = canonical_id || '_x'")
        conn.commit()
    retriever = HybridRetriever(store, client=OpenRouterClient())
    assert retriever._lookup_direct_article("test_code", "5-modda") is None
    assert retriever._lookup_direct_article("test_code", "15-modda") == "test_code_art_15_x"


@pytest.mark.asyncio
async def test_retrieval_degrades_to_bm25_when_embeddings_fail():
    class BrokenEmbeddings(OpenRouterClient):
        async def get_embeddings(self, texts, model=None):
            raise RuntimeError("embedding service down")

    retriever = HybridRetriever(get_store(), client=BrokenEmbeddings())
    results = await retriever.retrieve("tibbiy yordam nogironligi bo'lgan shaxslar", top_k=5)
    assert results
    assert all(r.vector_rank is None for r in results)


def test_vector_store_sees_writes_made_through_another_handle(tmp_path):
    a = LanceVectorStore(str(tmp_path))
    b = LanceVectorStore(str(tmp_path))
    vec = [0.1] * settings.EMBEDDING_DIMENSION

    def rec(cid):
        return {"canonical_id": cid, "vector": vec, "language": "uz", "status": "active",
                "category": "c", "disability_types": "[]", "embedding_model_version": "v"}

    a.upsert_vectors([rec("a_art_1")])
    b.upsert_vectors([rec("b_art_1")])
    assert {r["canonical_id"] for r in a.search_vector(vec, top_k=10)} == {"a_art_1", "b_art_1"}


def test_vector_store_handles_quotes_in_canonical_ids(tmp_path):
    store = LanceVectorStore(str(tmp_path))
    vec = [0.2] * settings.EMBEDDING_DIMENSION
    rec = lambda cid: {"canonical_id": cid, "vector": vec, "language": "uz", "status": "active",
                       "category": "c", "disability_types": "[]", "embedding_model_version": "v"}
    keep, tricky = "keep_art_1", "o'rq_1'OR'1'='1"
    store.upsert_vectors([rec(keep), rec(tricky)])
    store.upsert_vectors([rec(tricky)])  # re-index must replace, not duplicate or wipe other rows
    assert store.count() == 2
    store.delete_by_canonical_id(tricky)
    assert [r["canonical_id"] for r in store.search_vector(vec, top_k=10)] == [keep]


@pytest.mark.asyncio
async def test_failed_embedding_leaves_the_stored_article_untouched(tmp_path):
    store = await _store_with_articles(tmp_path, ["7"])
    original = store.get_article("test_code_art_7")
    original_text = original.get_text("uz")

    edited = original.model_copy(deep=True)
    edited.translations["uz"] = "YANGI MATN, hali saqlanmagan"

    class BrokenEmbeddings(OpenRouterClient):
        async def get_embeddings(self, texts, model=None):
            raise RuntimeError("embedding service down")

    with pytest.raises(RuntimeError):
        await store.index_article(edited, client=BrokenEmbeddings())

    assert store.get_article("test_code_art_7").get_text("uz") == original_text
    assert not store.fts_store.bm25_search("YANGI MATN saqlanmagan", language="uz", top_k=3)


@pytest.mark.asyncio
async def test_failed_edit_does_not_leak_into_the_shared_cached_article(monkeypatch):
    store = get_store()
    before = store.get_article("law_disability_2020_art_15").get_text("uz")

    async def boom(self, article, client=None):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(HybridStore, "index_article", boom)
    async with local_client() as c:
        res = await c.put("/api/v1/inclusive/norms/law_disability_2020_art_15", json={"text_uz": "DRAFT TEXT"})
    assert res.status_code == 502
    assert store.get_article("law_disability_2020_art_15").get_text("uz") == before


# ----------------------------------------------------------------------------------------------------------
# Cache and generation errors
# ----------------------------------------------------------------------------------------------------------

def test_cache_returns_independent_copies():
    cache = get_cache()
    answer = "Tibbiy yordam bepul ko'rsatiladi. " * 15
    cache.set("copy isolation probe", "uz", "plain", {"answer": answer, "citations": [], "flags": {"x": 1}})
    first = cache.get("copy isolation probe", "uz", "plain")
    first["answer"] = "MUTATED"
    first["flags"]["x"] = 99
    second = cache.get("copy isolation probe", "uz", "plain")
    assert second["answer"] == answer
    assert second["flags"]["x"] == 1


@pytest.mark.asyncio
async def test_answers_failing_validation_are_not_cached(monkeypatch):
    long_answer = "Javob matni. " * 60

    async def fake_generate(self, query, contexts, language="uz", mode="plain"):
        return GeneratedAnswer(
            answer=long_answer, clean_answer=long_answer, telegram_formatted=long_answer, citations=[],
            is_refusal=False, validation_passed=False, language=language, mode=mode,
        )

    monkeypatch.setattr(AnswerGenerator, "generate_answer", fake_generate)
    question = "Nogironligi bo'lgan shaxslar uchun transport imtiyozlari qanday tartibda beriladi?"
    async with local_client() as c:
        first = await c.post("/api/v1/query", json={"question": question, "language": "uz"})
        second = await c.post("/api/v1/query", json={"question": question, "language": "uz"})
    assert first.status_code == second.status_code == 200
    assert first.json()["validation_passed"] is False
    assert second.json()["cached"] is False


@pytest.mark.asyncio
async def test_llm_outage_returns_503_instead_of_a_stack_trace(monkeypatch):
    async def down(self, *args, **kwargs):
        raise RuntimeError("All configured LLM models failed on OpenRouter.")

    monkeypatch.setattr(OpenRouterClient, "chat_completion", down)
    async with local_client() as c:
        res = await c.post(
            "/api/v1/query",
            json={"question": "Nogironlik guruhini qayta ko'rikdan o'tkazish tartibi qanday?", "language": "uz"},
        )
    assert res.status_code == 503
    assert "OpenRouter" not in res.text


@pytest.mark.asyncio
async def test_stream_failure_is_a_structured_error_not_answer_text(monkeypatch):
    async def broken_stream(self, *args, **kwargs):
        raise RuntimeError("All configured LLM models failed to stream (HTTP 401).")
        yield  # pragma: no cover  (makes this an async generator)

    monkeypatch.setattr(OpenRouterClient, "chat_completion_stream", broken_stream)
    async with local_client() as c:
        res = await c.post(
            "/api/v1/query?stream=true",
            json={"question": "Nogironlik guruhini qayta ko'rikdan o'tkazish tartibi qanday?", "language": "uz"},
        )
    events = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "error"
    assert not any(e.get("type") == "done" for e in events)
    assert "HTTP 401" not in res.text


@pytest.mark.asyncio
async def test_stream_done_event_carries_the_sanitized_answer():
    async with local_client() as c:
        res = await c.post(
            "/api/v1/query?stream=true",
            json={"question": "Nogironligi bo'lgan shaxslarga tibbiy yordam qanday ko'rsatiladi?", "language": "uz"},
        )
    events = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
    done = events[-1]
    assert done["type"] == "done"
    assert done["clean_answer"]
    assert "_art_" not in done["clean_answer"]


# ----------------------------------------------------------------------------------------------------------
# Admin route correctness
# ----------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_article_status_is_rejected_not_half_applied():
    async with local_client() as c:
        res = await c.put(
            "/api/v1/admin/article/law_disability_2020_art_15",
            json={"title_uz": "t", "text_uz": "matn", "status": "archived-ish", "revectorize": False},
        )
    assert res.status_code == 422
    assert get_store().get_article("law_disability_2020_art_15").get_text("uz") != "matn"


@pytest.mark.asyncio
async def test_non_utf8_upload_is_a_client_error():
    async with local_client() as c:
        res = await c.post(
            "/api/v1/admin/upload",
            files={"file": ("law.txt", "Qonun matni".encode("cp1251") + b"\xff\xfe\xfa", "text/plain")},
        )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_ingest_url_classifies_regulations_from_the_supplied_url(monkeypatch):
    from src.ingestion import universal_engine

    captured = {}

    async def fake_ingest(self, spec, http_client, force_reindex=False):
        captured["spec"] = spec
        return 0

    monkeypatch.setattr(universal_engine.UniversalAutonomousEngine, "ingest_spec", fake_ingest)
    async with local_client() as c:
        res = await c.post(
            "/api/v1/admin/ingest-url", json={"url": "https://www2.lex.uz/uz/docs/-6445145?title=vazirlar-mahkamasi-qarori"}
        )
    assert res.status_code == 422  # zero articles extracted by the fake engine
    spec = captured["spec"]
    assert spec.slug == "doc_6445145"          # not "doc_2" (digit of "www2")
    assert spec.category == "regulations"
    assert spec.parser_type == "regulation_clause"


@pytest.mark.asyncio
async def test_corpus_changes_invalidate_cached_answers():
    cache = get_cache()
    cache.set("invalidate me", "uz", "plain", {"answer": "Matn. " * 80})
    assert cache.get("invalidate me", "uz", "plain") is not None
    async with local_client() as c:
        art = get_store().get_article("law_disability_2020_art_15")
        res = await c.put(
            "/api/v1/inclusive/norms/law_disability_2020_art_15",
            json={"text_uz": art.get_text("uz")},  # same text, still a write
        )
    assert res.status_code == 200
    assert cache.get("invalidate me", "uz", "plain") is None


# ----------------------------------------------------------------------------------------------------------
# URL importer
# ----------------------------------------------------------------------------------------------------------

LAW_HTML = """
<html><head><title>PF-1-сон 01.01.2025. Sinov farmoni</title></head><body><div class="document">
<p>1-modda. Asosiy qoida</p><p>Nogironligi bo'lgan shaxslarga barcha imtiyozlar kafolatlanadi.</p>
</div></body></html>
""".strip().encode("utf-8")


class _Resp:
    status_code = 200
    headers = {"content-disposition": 'attachment;filename="PF-1 01.01.2025.doc"'}

    def __init__(self, content):
        self.content = content
        self.text = content.decode("utf-8")


@pytest.mark.asyncio
async def test_importer_does_not_clobber_another_laws_file(tmp_path, monkeypatch):
    from src.ingestion.url_importer import LexUrlImporter, UrlImportRequest

    qonunlar = tmp_path / "qonunlar"
    qonunlar.mkdir()
    other = qonunlar / "PF-115.doc"
    other.write_bytes(b"another law, must survive")

    async def fake_get(self, url, headers=None):
        return _Resp(LAW_HTML)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    store = HybridStore(str(tmp_path / "store"))
    importer = LexUrlImporter(store=store, qonunlar_dir=str(qonunlar))
    res = await importer.import_from_url(UrlImportRequest(url="https://lex.uz/uz/docs/-1"))

    assert res.status == "new"
    assert other.exists() and other.read_bytes() == b"another law, must survive"


@pytest.mark.asyncio
async def test_failed_indexing_does_not_mark_document_as_imported(tmp_path, monkeypatch):
    from src.ingestion.url_importer import LexUrlImporter, UrlImportRequest

    async def fake_get(self, url, headers=None):
        return _Resp(LAW_HTML)

    class BrokenEmbeddings(OpenRouterClient):
        async def get_embeddings(self, texts, model=None):
            raise RuntimeError("embedding service down")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    qonunlar = tmp_path / "qonunlar"
    store = HybridStore(str(tmp_path / "store"))
    store._default_client = BrokenEmbeddings()
    importer = LexUrlImporter(store=store, qonunlar_dir=str(qonunlar))

    with pytest.raises(RuntimeError):
        await importer.import_from_url(UrlImportRequest(url="https://lex.uz/uz/docs/-1"))
    assert list(qonunlar.glob("*.doc")) == []  # otherwise the retry would be reported as "unchanged"

    store._default_client = OpenRouterClient()
    retry = await importer.import_from_url(UrlImportRequest(url="https://lex.uz/uz/docs/-1"))
    assert retry.status == "new" and retry.articles_imported >= 1
