"""The public endpoints: per-address limits, administrative bulk reads and a /health that publishes only the status."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from src.api.app import app
from src.api.middleware.rate_limiter import SlidingWindowLimiter
from src.config import settings

ARTICLE = "/api/v1/article/law_disability_2020_art_35"


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture
def deployment(monkeypatch):
    """A deployment: an administrator key is configured, so a request without it is an ordinary visitor."""
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "deployment-key")
    return {"X-Admin-Key": "deployment-key"}


@pytest.mark.asyncio
async def test_reading_one_article_is_rate_limited_per_address(deployment, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BROWSE_RATE_PER_MINUTE", 2)
    async with _client() as c:
        statuses = [(await c.get(ARTICLE)).status_code for _ in range(3)]
        limited = await c.get(ARTICLE)
        admin = await c.get(ARTICLE, headers=deployment)       # the dashboard reads the same endpoints: not limited
    assert statuses == [200, 200, 429]
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1
    assert admin.status_code == 200


@pytest.mark.asyncio
async def test_the_browsing_endpoints_share_one_budget_that_the_questions_do_not_use(deployment, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BROWSE_RATE_PER_MINUTE", 1)
    async with _client() as c:
        first = await c.get("/api/v1/inclusive/norms?limit=1")
        second = await c.get("/api/v1/inclusive/documents")
        question = await c.post("/api/v1/query", json={"question": "Nogironlik pensiyasi qancha?"})
    assert first.status_code == 200 and second.status_code == 429
    assert question.status_code == 200                           # asking is not browsing


@pytest.mark.asyncio
async def test_the_whole_corpus_can_only_be_paged_through_by_an_administrator(deployment):
    async with _client() as c:
        anonymous = await c.get("/api/v1/articles?limit=1")
        admin = await c.get("/api/v1/articles?limit=1", headers=deployment)
    assert anonymous.status_code == 401
    assert admin.status_code == 200 and len(admin.json()) == 1


@pytest.mark.asyncio
async def test_the_public_feedback_form_has_its_own_strict_limit(monkeypatch):
    monkeypatch.setattr(settings, "FEEDBACK_RATE_PER_MINUTE", 2)
    body = {"query": "Savol?", "answer": "Javob.", "rating": 5}
    async with _client() as c:
        statuses = [(await c.post("/api/v1/feedback", json=body)).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]


@pytest.mark.asyncio
async def test_the_public_stats_do_not_publish_api_key_metrics():
    async with _client() as c:
        data = (await c.get("/api/v1/inclusive/stats")).json()
    assert data["total_statutory_norms"] > 0
    assert "active_api_keys" not in data and "total_api_requests_served" not in data


@pytest.mark.asyncio
async def test_health_publishes_only_the_status_and_the_details_are_administrative(deployment):
    async with _client() as c:
        public = (await c.get("/health")).json()
        anonymous = await c.get("/health/details")
        admin = await c.get("/health/details", headers=deployment)
    assert set(public) == {"status", "service", "version"}
    assert anonymous.status_code == 401
    assert admin.status_code == 200 and {"rss_memory_mb", "openrouter_budget", "articles_indexed"} <= set(admin.json())


def test_the_limiter_answers_with_the_seconds_until_a_slot_frees_up():
    limiter = SlidingWindowLimiter(window_s=60.0, default_limit=2)
    assert limiter.hit("k", now=100.0) is None and limiter.hit("k", now=110.0) is None
    assert limiter.hit("k", now=120.0) == 41                      # the first hit leaves the window at t=160
    assert limiter.hit("k", now=161.0) is None
    assert limiter.hit("blocked", limit=0, now=0.0) == 60         # an explicit 0 blocks, even with no earlier hit


@pytest.mark.asyncio
async def test_a_failing_retrieval_cancels_the_paid_scope_call_it_started(monkeypatch):
    """Only a failure of the first search used to cancel the helper tasks: a later failure left the Jev call running."""
    from src.nlp.query_analyzer import QueryAnalyzer
    from src.retrieval import pipeline

    cancelled = asyncio.Event()

    class FakeRetriever:
        def __init__(self, *args, **kwargs):
            pass

        async def retrieve(self, *args, **kwargs):
            await asyncio.sleep(0)                  # the scope call gets to start while the search is "in flight"
            return []

    class FakeJev:
        def __init__(self, client):
            pass

        async def scope(self, query):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

    def broken_expand(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline, "HybridRetriever", FakeRetriever)
    monkeypatch.setattr(pipeline, "JevRanker", FakeJev)
    monkeypatch.setattr(pipeline, "expand_cross_references", broken_expand)
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "jev")
    monkeypatch.setattr(settings, "QUERY_NORMALIZE_UZ", False)

    analysis = QueryAnalyzer.analyze("Nogironlik pensiyasi qancha?")
    with pytest.raises(RuntimeError, match="boom"):
        await pipeline.retrieve_contexts(analysis=analysis, store=object(), client=SimpleNamespace(is_mock=False))
    await asyncio.sleep(0)
    assert cancelled.is_set()
