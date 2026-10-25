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
async def test_defaults_ask_qwen3_for_1024_dimensions_without_an_instruction(monkeypatch):
    c = _client(monkeypatch)
    await c.get_query_embeddings(["Savol?"])
    assert c._http_client.payloads == [{"model": "qwen/qwen3-embedding-8b", "input": ["Savol?"], "dimensions": 1024}]


@pytest.mark.asyncio
async def test_a_model_without_adjustable_size_gets_no_dimensions_field(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "baai/bge-m3")
    monkeypatch.setattr(settings, "EMBEDDING_REQUEST_DIMENSIONS", 0)
    c = _client(monkeypatch)
    await c.get_query_embeddings(["Savol?"])
    assert c._http_client.payloads == [{"model": "baai/bge-m3", "input": ["Savol?"]}]


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


@pytest.mark.asyncio
async def test_another_model_gets_its_native_size(monkeypatch):
    c = _client(monkeypatch)
    await c.get_embeddings(["Modda matni."], model="baai/bge-m3")
    assert c._http_client.payloads == [{"model": "baai/bge-m3", "input": ["Modda matni."]}]


@pytest.mark.asyncio
async def test_the_translation_audit_embeds_with_its_calibrated_model(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("audit_translations", "scripts/audit_translations.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    asked = []

    class FakeClient:
        embedding_is_mock = False

        async def get_embeddings(self, texts, model=None):
            asked.append(model)
            return [[1.0, 0.0] for _ in texts]

        async def close(self):
            pass

    monkeypatch.setattr(audit, "OpenRouterClient", FakeClient)
    monkeypatch.setattr(audit, "CACHE_DIR", tmp_path)
    vecs = await audit.embed_cached({"a_p_1": ("Matn", "Текст")}, "ru")
    assert asked == ["baai/bge-m3"] and list(vecs) == ["a_p_1"]       # whatever EMBEDDING_MODEL the service uses
