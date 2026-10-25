"""The store records which embedding model made its vectors and never mixes two models (src/storage/hybrid_store.py)."""
import json

import pytest

from src.clients.openrouter import OpenRouterClient
from src.config import settings
from src.retrieval.hybrid_retriever import HybridRetriever
from src.schema.canonical import ArticleMetadata, CanonicalArticle
from src.storage.hybrid_store import EMBEDDING_MARKER, HybridStore


def _article(cid="law_m_art_1", text="Nogironligi bo'lgan shaxslarga yillik ta'til 30 kun beriladi."):
    return CanonicalArticle(
        canonical_id=cid,
        metadata=ArticleMetadata(
            law_id="law_m", law_title={"uz": "Qonun"}, law_number="O'RQ-1", article_number="1-modda",
            article_title={"uz": "Ta'til"}, source_url="https://lex.uz/docs/1", effective_date="2022-01-01",
            last_verified_date="2022-01-01", source_hash=f"sha256:{cid}", category="labor"),
        translations={"uz": text},
    )


@pytest.mark.asyncio
async def test_the_first_vectors_record_the_model_and_each_row_names_it(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "qwen/qwen3-embedding-8b")
    monkeypatch.setattr(settings, "EMBEDDING_REQUEST_DIMENSIONS", 1024)
    store = HybridStore(str(tmp_path / "s"))
    await store.index_articles_batch([_article()], client=OpenRouterClient())
    assert json.loads((tmp_path / "s" / EMBEDDING_MARKER).read_text()) == {"model": "qwen/qwen3-embedding-8b", "dimensions": 1024}
    assert set(store.vector_store.models()) == {"qwen/qwen3-embedding-8b"}          # not the label of the article's metadata
    assert store.embedding_mismatch() == ""


@pytest.mark.asyncio
async def test_vectors_of_another_model_are_refused_until_the_whole_store_is_re_embedded(tmp_path, monkeypatch):
    store = HybridStore(str(tmp_path / "s"))
    client = OpenRouterClient()
    await store.index_article(_article(), client=client)                    # the configured default model
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "another/model")
    reopened = HybridStore(str(tmp_path / "s"))
    assert "another/model" in reopened.embedding_mismatch()
    with pytest.raises(RuntimeError, match="mix embedding models"):
        await reopened.index_article(_article("law_m_art_2"), client=client)
    with pytest.raises(RuntimeError, match="mix embedding models"):
        await reopened.reembed_articles([_article()], client=client)
    # a full re-embedding with the new model is allowed; the script records the model when every unit is done
    assert await reopened.reembed_articles([_article()], client=client, new_model=True) == 1
    reopened.write_embedding_marker()
    assert reopened.embedding_mismatch() == ""


@pytest.mark.asyncio
async def test_retrieval_skips_vectors_of_another_model(tmp_path, monkeypatch):
    store = HybridStore(str(tmp_path / "s"))
    client = OpenRouterClient()
    await store.index_article(_article(), client=client)
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "another/model")
    reopened = HybridStore(str(tmp_path / "s"))
    searched = []
    monkeypatch.setattr(reopened.vector_store, "search_vector", lambda **kw: searched.append(kw) or [])
    results = await HybridRetriever(reopened, client).retrieve("yillik ta'til nogironligi bo'lgan", top_k=5)
    assert searched == []                                                   # no dense search at all
    assert [r.canonical_id for r in results] == ["law_m_art_1"]             # full-text search still answers


def test_a_store_made_before_the_marker_is_not_called_mismatched(tmp_path):
    store = HybridStore(str(tmp_path / "old"))
    assert store.stored_embedding() is None and store.embedding_mismatch() == ""


@pytest.mark.asyncio
async def test_a_full_re_embedding_records_the_new_model(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("reembed_context", "scripts/reembed_context.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "baai/bge-m3")                # the store's old model
    store = HybridStore(str(tmp_path / "s"))
    await store.index_articles_batch([_article(), _article("law_m_art_2")], client=OpenRouterClient())
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "qwen/qwen3-embedding-8b")
    assert HybridStore(str(tmp_path / "s")).embedding_mismatch()
    # a partial run leaves the marker: the store is not all of one model yet
    assert await script.main(["--store-dir", str(tmp_path / "s"), "--all", "--allow-mock", "--no-optimize", "--limit", "1"]) == 1
    assert HybridStore(str(tmp_path / "s")).embedding_mismatch()
    assert await script.main(["--store-dir", str(tmp_path / "s"), "--all", "--allow-mock", "--no-optimize"]) == 0
    done = HybridStore(str(tmp_path / "s"))
    assert done.embedding_mismatch() == "" and done.stored_embedding()["model"] == "qwen/qwen3-embedding-8b"
    assert set(done.vector_store.models()) == {"qwen/qwen3-embedding-8b"}
