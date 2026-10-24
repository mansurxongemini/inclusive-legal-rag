"""One OpenRouter key and one endpoint for every call; the settings of the old Meta test provider are gone."""
import httpx
import pytest

from src.clients.openrouter import OpenRouterClient
from src.config import REMOVED_SETTINGS, Settings, removed_settings_in_use


def test_the_second_provider_and_its_side_endpoints_are_not_settings_any_more():
    assert not [name for name in REMOVED_SETTINGS if name in Settings.model_fields]
    assert {"OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "GENERATION_MODEL_PRIMARY"} <= set(Settings.model_fields)


def test_a_leftover_setting_is_reported_not_silently_dropped(monkeypatch, tmp_path):
    for name in REMOVED_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("PLUS_META_AI_API_KEY=leftover\nUTILITY_MODEL=\nOPENROUTER_API_KEY=fine\n", encoding="utf-8")
    monkeypatch.setenv("GENERATION_MODEL_FALLBACK", "muse-spark-1.3")
    # an empty value says nothing; a current setting is not "removed"
    assert removed_settings_in_use(str(env_file)) == ["GENERATION_MODEL_FALLBACK", "PLUS_META_AI_API_KEY"]
    assert removed_settings_in_use(str(tmp_path / "missing.env")) == ["GENERATION_MODEL_FALLBACK"]
    # an experiment that was measured and dropped is reported the same way: its switch does nothing any more
    monkeypatch.setenv("FTS_STOPWORDS", "true")
    assert removed_settings_in_use(str(tmp_path / "missing.env")) == ["FTS_STOPWORDS", "GENERATION_MODEL_FALLBACK"]


def test_the_client_has_no_side_endpoints_or_second_key():
    c = OpenRouterClient()
    for gone in ("get_embedding_client", "get_jev_client", "get_utility_client", "utility_chat", "_rotate_main_key",
                 "embedding_base_url", "jev_base_url", "utility_base_url", "fallback_model"):
        assert not hasattr(c, gone), gone


@pytest.mark.asyncio
async def test_chat_embeddings_reranking_and_jev_all_go_through_the_one_client(tmp_path, monkeypatch):
    from src.clients.spend import SpendLedger

    monkeypatch.setattr("src.clients.openrouter.ledger", SpendLedger(path=str(tmp_path / "s.db"), scope="service"))
    monkeypatch.setattr(OpenRouterClient, "embedding_is_mock", property(lambda self: False))
    urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        path = request.url.path
        if path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]})
        if path.endswith("/rerank"):
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}]})
        if path.endswith("/decisions"):
            return httpx.Response(200, json={"answers": {}, "usage": {}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Javob matni yetarlicha uzun bo'lishi kerak."}}]})

    c = OpenRouterClient()
    c.is_mock = False
    c.api_key, c.base_url = "the-one-key", "https://openrouter.ai/api/v1"
    real = await c.get_client()
    assert real.headers["Authorization"] == "Bearer the-one-key"
    await real.aclose()
    c._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    served = {"n": 0}
    original = c.get_client

    async def counting_client():
        served["n"] += 1
        return await original()

    monkeypatch.setattr(c, "get_client", counting_client)

    await c.chat_completion([{"role": "user", "content": "savol"}])
    await c.get_embeddings(["savol"])
    await c.rerank_documents("savol", ["hujjat"])
    await c.decide("state", {"q": {"type": "choice", "instructions": "x", "criteria": {"a": "b"}}})

    assert served["n"] == 4
    assert [u.split("/api/")[1] for u in urls] == ["v1/chat/completions", "v1/embeddings", "v1/rerank", "alpha/decisions"]
    assert all(u.startswith("https://openrouter.ai/api/") for u in urls)
