"""Embedding options for instruction-tuned models (qwen3-embedding): output size and a question-only instruction."""
import pytest

from src.clients.openrouter import OpenRouterClient
from src.config import settings


class Http:
    is_closed = False

    def __init__(self):
        self.payloads = []

    async def post(self, url, json=None, **kw):
        self.payloads.append(json)

        class R:
            status_code = 200

            def json(self_inner):
                return {"data": [{"embedding": [0.0] * 4, "index": i} for i in range(len(json["input"]))]}
        return R()


def _client(monkeypatch):
    monkeypatch.setattr(settings, "MOCK_EXTERNAL_APIS", False)
    c = OpenRouterClient()
    c.api_key = "test-key"
    c._http_client = Http()
    return c


@pytest.mark.asyncio
async def test_defaults_send_the_bge_m3_request_unchanged(monkeypatch):
    c = _client(monkeypatch)
    await c.get_query_embeddings(["Savol?"])
    assert c._http_client.payloads == [{"model": settings.EMBEDDING_MODEL, "input": ["Savol?"]}]


@pytest.mark.asyncio
async def test_dimensions_and_the_instruction_go_to_questions_only(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(settings, "EMBEDDING_REQUEST_DIMENSIONS", 1024)
    monkeypatch.setattr(settings, "EMBEDDING_QUERY_INSTRUCTION", "Retrieve the legal provision that answers the question")
    await c.get_query_embeddings(["Savol?"])
    await c.get_embeddings(["Modda matni."])
    question, unit = c._http_client.payloads
    assert question["dimensions"] == 1024 and unit["dimensions"] == 1024
    assert question["input"] == ["Instruct: Retrieve the legal provision that answers the question\nQuery: Savol?"]
    assert unit["input"] == ["Modda matni."]
