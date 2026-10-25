"""
Regression tests for the issues found in the project review:
access control, SSRF, citation validation, retrieval correctness, cache and storage consistency.
"""
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app, get_cache, get_store
from src.clients.openrouter import OpenRouterClient
from src.config import settings
from src.generation.generator import AnswerGenerator, GeneratedAnswer
from src.generation.validator import CitationValidator
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

ADMIN_PATH = "/api/v1/admin/stats"

ADMIN_CALLS = [
    ("post", "/api/v1/admin/corpus/preview", {"source": "-1"}),
    ("post", "/api/v1/admin/corpus/add", {"lex_id": "-1", "include": "all"}),
    ("post", "/api/v1/admin/corpus/refresh", {"lex_id": "-1"}),
    ("get", "/api/v1/admin/corpus/jobs/job_abc", None),
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
        res = await c.get(ADMIN_PATH, headers={"Referer": "http://attacker.example:8000/"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_proxy_headers_disable_loopback_trust():
    # nginx on the same host shows up as 127.0.0.1 but always forwards the real client address
    async with local_client() as c:
        res = await c.get(ADMIN_PATH, headers={"X-Forwarded-For": "198.51.100.9"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_direct_loopback_keeps_dashboard_working():
    async with local_client() as c:
        res = await c.get(ADMIN_PATH)
    assert res.status_code == 200


LOCAL_PEER = ("127.0.0.1", 40000)


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    {"Host": "evil.example"},                                                  # DNS rebinding to 127.0.0.1
    {"Host": "evil.example:8000"},
    {"Origin": "http://evil.example"},                                         # another site driving the browser
    {"Origin": "null"},
    {"Origin": "http://localhost:3000"},                                       # same host, other port = other site
    {"Sec-Fetch-Site": "cross-site"},
])
async def test_loopback_trust_ignores_requests_driven_by_other_web_pages(headers):
    async with local_client() as c:
        res = await c.get(ADMIN_PATH, headers=headers)
    assert res.status_code == 401, headers


@pytest.mark.asyncio
@pytest.mark.parametrize("base_url,headers", [
    ("http://localhost:8000", {"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"}),
    ("http://127.0.0.1:8000", {"Origin": "http://127.0.0.1:8000"}),
    ("http://[::1]:8000", {}),
    ("http://localhost", {"Sec-Fetch-Site": "none"}),
])
async def test_loopback_trust_keeps_the_dashboard_working(base_url, headers):
    async with AsyncClient(transport=ASGITransport(app=app, client=LOCAL_PEER), base_url=base_url) as c:
        res = await c.get(ADMIN_PATH, headers=headers)
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_loopback_trust_can_be_switched_off_behind_a_proxy(monkeypatch):
    # nginx without X-Forwarded-For: the caller is indistinguishable from a local one, so only the key may count
    monkeypatch.setattr(settings, "ADMIN_LOOPBACK_ENABLED", False)
    async with local_client() as c:
        assert (await c.get(ADMIN_PATH)).status_code == 401
        monkeypatch.setattr(settings, "ADMIN_API_KEY", "s3cret-admin-key")
        assert (await c.get(ADMIN_PATH)).status_code == 401
        assert (await c.get(ADMIN_PATH, headers={"X-Admin-Key": "s3cret-admin-key"})).status_code == 200
        assert (await c.get(ADMIN_PATH, headers={"X-Admin-Key": "nope"})).status_code == 403


@pytest.mark.asyncio
async def test_admin_key_grants_remote_access(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "s3cret-admin-key")
    async with remote_client() as c:
        ok = await c.get(ADMIN_PATH, headers={"X-Admin-Key": "s3cret-admin-key"})
        bearer = await c.get("/api/v1/feedback", headers={"Authorization": "Bearer s3cret-admin-key"})
        wrong = await c.get(ADMIN_PATH, headers={"X-Admin-Key": "nope"})
    assert ok.status_code == 200
    assert bearer.status_code == 200
    assert wrong.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [
    ("post", "/api/v1/inclusive/query"),                 # the old keyed endpoint: gone
    ("get", "/api/v1/inclusive/admin/api-keys"),
    ("post", "/api/v1/inclusive/admin/api-keys"),
    ("delete", "/api/v1/inclusive/admin/api-keys/key_abc"),
])
async def test_old_incl_key_system_is_gone(method, path):
    async with local_client() as c:
        res = await c.request(method.upper(), path, json={"question": "x", "name": "x"})
    assert res.status_code in (404, 405), f"{method.upper()} {path} -> {res.status_code}"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/api/v1/inclusive/categories",
    "/api/v1/inclusive/norms",
    "/api/v1/inclusive/documents",
    "/api/v1/inclusive/stats",
])
async def test_public_browsing_stays_open_to_remote_callers(path):
    async with remote_client() as c:
        res = await c.get(path)
    assert res.status_code == 200, path


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
        get_query_embeddings = get_embeddings          # questions and units are embedded alike here

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
        get_query_embeddings = get_embeddings          # questions and units are embedded alike here

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
        res = await c.put("/api/v1/admin/article/law_disability_2020_art_15", json={"title_uz": "Modda", "text_uz": "DRAFT TEXT"})
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
async def test_llm_outage_serves_the_matching_norms_not_an_error_page(monkeypatch):
    async def down(self, *args, **kwargs):
        raise RuntimeError("All configured LLM models failed on OpenRouter.")

    monkeypatch.setattr(OpenRouterClient, "chat_completion", down)
    question = "Nogironlik guruhini qayta ko'rikdan o'tkazish tartibi qanday?"
    async with local_client() as c:
        res = await c.post("/api/v1/query", json={"question": question, "language": "uz"})
        again = await c.post("/api/v1/query", json={"question": question, "language": "uz"})
    assert res.status_code == 200
    body = res.json()
    assert body["degraded"] is True and body["citations"]
    assert any(w.startswith("llm_unavailable") for w in body["warnings"])
    assert "ishlamayapti" in body["answer"] and "OpenRouter" not in res.text
    assert again.json()["cached"] is False            # a sources-only answer is never cached


@pytest.mark.asyncio
async def test_stream_failure_before_any_token_serves_the_matching_norms(monkeypatch):
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
    assert events[-1]["type"] == "done" and events[-1]["degraded"] is True and events[-1]["citations"]
    assert "HTTP 401" not in res.text


@pytest.mark.asyncio
async def test_stream_interrupted_after_tokens_is_a_structured_error(monkeypatch):
    async def half_stream(self, *args, **kwargs):
        yield "Javobning boshi "
        raise RuntimeError("LLM stream was interrupted.")

    monkeypatch.setattr(OpenRouterClient, "chat_completion_stream", half_stream)
    async with local_client() as c:
        res = await c.post(
            "/api/v1/query?stream=true",
            json={"question": "Nogironlik guruhini qayta ko'rikdan o'tkazish tartibi qanday?", "language": "uz"},
        )
    events = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "error"
    assert not any(e.get("type") == "done" for e in events)


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
async def test_corpus_changes_invalidate_cached_answers():
    cache = get_cache()
    cache.set("invalidate me", "uz", "plain", {"answer": "Matn. " * 80})
    assert cache.get("invalidate me", "uz", "plain") is not None
    async with local_client() as c:
        art = get_store().get_article("law_disability_2020_art_15")
        res = await c.put(
            "/api/v1/admin/article/law_disability_2020_art_15",
            json={"title_uz": "15-modda", "text_uz": art.get_text("uz")},  # same text, still a write
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

