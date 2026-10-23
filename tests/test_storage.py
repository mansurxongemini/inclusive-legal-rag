import pytest
import shutil
from pathlib import Path
from src.schema.canonical import CanonicalArticle
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient


@pytest.mark.asyncio
async def test_hybrid_store_indexing_and_retrieval(tmp_path):
    temp_dir = tmp_path / "test_store"
    store = HybridStore(str(temp_dir))
    client = OpenRouterClient()

    # Seed pilot file
    pilot_file = Path("tests/fixtures/synthetic_pilot.json")
    await store.seed_from_file(str(pilot_file), client=client)

    assert store.count() >= 8

    # Fetch specific article
    art15 = store.get_article("synthetic_law_art_15")
    assert art15 is not None
    assert art15.canonical_id == "synthetic_law_art_15"
    assert "tibbiy yordam" in art15.get_text("uz").lower()

    # FTS search
    fts_results = store.fts_store.bm25_search("tibbiy yordam", language="uz", top_k=5)
    assert len(fts_results) > 0
    found_ids = [r["canonical_id"] for r in fts_results]
    assert "synthetic_law_art_15" in found_ids

    # Vector search
    query_vec = (await client.get_embeddings(["Nogironlarga tibbiy xizmat va dori-darmonlar"]))[0]
    vec_results = store.vector_store.search_vector(query_vec, top_k=5, language="uz")
    assert len(vec_results) > 0

    # Delete test
    old_sample = store.get_article("synthetic_law_old_sample_art_10")
    assert old_sample is not None
    store.delete_article("synthetic_law_old_sample_art_10")
    assert store.get_article("synthetic_law_old_sample_art_10") is None


def test_fts_article_cache_is_stale_after_external_write_until_cleared(tmp_path):
    """The corpus build script is a separate process: its writes never pass through the server's cache, so a
    repealed act kept being served as active until clear_article_cache() existed and was called."""
    import json
    from src.storage.fts_store import SqliteFtsStore

    db = str(tmp_path / "fts.db")
    server = SqliteFtsStore(db)
    article = CanonicalArticle.model_validate(json.loads(Path("tests/fixtures/synthetic_pilot.json").read_text("utf-8"))[0])
    server.upsert_article(article)
    cid = article.canonical_id
    assert server.get_article(cid).metadata.status.value == "active"      # now cached

    other_process = SqliteFtsStore(db)
    repealed = article.model_copy(deep=True)
    repealed.metadata.status = type(article.metadata.status)("repealed")
    other_process.upsert_article(repealed)

    assert server.get_article(cid).metadata.status.value == "active"      # the cache hides the change
    server.clear_article_cache()
    assert server.get_article(cid).metadata.status.value == "repealed"
    assert server.get_articles_batch([cid])[cid].metadata.status.value == "repealed"


from datetime import timedelta
from src.schema.canonical import ArticleMetadata
from src.storage.chunking import build_chunks
from scripts.reembed_context import main as reembed_main


@pytest.mark.asyncio
async def test_reembed_articles(tmp_path, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "VECTOR_EXCLUDE_LANGUAGES", "")          # this test is about both languages
    store_dir = tmp_path / "test_reembed_store"
    store = HybridStore(str(store_dir))
    client = OpenRouterClient()

    art_with_ctx = CanonicalArticle(
        canonical_id="test_art_with_context",
        metadata=ArticleMetadata(
            law_id="law_1",
            law_title={"uz": "Qonun 1", "ru": "Закон 1"},
            law_number="O'RQ-1",
            article_number="1-modda",
            article_title={"uz": "Modda 1", "ru": "Статья 1"},
            source_url="https://lex.uz/docs/1",
            effective_date="2022-01-01",
            last_verified_date="2022-01-01",
            source_hash="sha256:art1",
            category="social_protection",
        ),
        translations={
            "uz": "Nogironligi bo'lgan shaxslar uchun imtiyozlar va ijtimoiy kafolatlar belgilanadi.",
            "ru": "Устанавливаются льготы и социальные гарантии для лиц с инвалидностью.",
        },
    )
    art_no_ctx = CanonicalArticle(
        canonical_id="test_art_no_context",
        metadata=ArticleMetadata(
            law_id="law_2",
            law_title={"uz": "Qonun 2", "ru": "Закон 2"},
            law_number="O'RQ-2",
            article_number="2-modda",
            article_title={"uz": "Modda 2", "ru": "Статья 2"},
            source_url="https://lex.uz/docs/2",
            effective_date="2022-01-01",
            last_verified_date="2022-01-01",
            source_hash="sha256:art2",
            category="social_protection",
        ),
        translations={
            "uz": "Mehnat munosabatlarini tartibga solish qoidalari.",
            "ru": "Правила регулирования трудовых отношений.",
        },
    )

    # 1. Initial index of both articles without context
    await store.index_articles_batch([art_with_ctx, art_no_ctx], client=client)

    orig_rows = store.vector_store.table.to_arrow().to_pylist()
    orig_vecs_with = [r["vector"] for r in orig_rows if r["canonical_id"] == art_with_ctx.canonical_id]
    orig_vecs_no = [r["vector"] for r in orig_rows if r["canonical_id"] == art_no_ctx.canonical_id]
    orig_fts_art = store.fts_store.get_article(art_with_ctx.canonical_id)

    # 2. Enrich art_with_ctx with chapter context; art_no_ctx remains without context
    art_with_ctx.metadata.chapter_number = "1-bob. Umumiy qoidalar"

    batches_done = []
    async def on_batch(cids):
        batches_done.extend(cids)

    # 3. Re-embed articles
    reembedded = await store.reembed_articles(
        [art_with_ctx, art_no_ctx],
        client=client,
        batch_size=1,
        concurrency=2,
        on_batch=on_batch,
    )
    assert reembedded == 2
    assert set(batches_done) == {art_with_ctx.canonical_id, art_no_ctx.canonical_id}

    # 4. Check new vectors in LanceDB
    new_rows = store.vector_store.table.to_arrow().to_pylist()
    new_vecs_with = [r["vector"] for r in new_rows if r["canonical_id"] == art_with_ctx.canonical_id]
    new_vecs_no = [r["vector"] for r in new_rows if r["canonical_id"] == art_no_ctx.canonical_id]

    # Vectors of unit with context change
    assert new_vecs_with != orig_vecs_with

    # Vectors of unit without context stay identical
    assert new_vecs_no == orig_vecs_no

    # Row count per canonical_id equals number of chunks across uz and ru
    expected_chunks_with = len(build_chunks(art_with_ctx, "uz")) + len(build_chunks(art_with_ctx, "ru"))
    assert len(new_vecs_with) == expected_chunks_with

    expected_chunks_no = len(build_chunks(art_no_ctx, "uz")) + len(build_chunks(art_no_ctx, "ru"))
    assert len(new_vecs_no) == expected_chunks_no

    # FTS is untouched
    current_fts_art = store.fts_store.get_article(art_with_ctx.canonical_id)
    assert current_fts_art.metadata.chapter_number != "1-bob. Umumiy qoidalar"
    assert current_fts_art.metadata.source_hash == orig_fts_art.metadata.source_hash

    # 5. Failing embedding client leaves old vectors intact
    class FailingClient:
        async def get_embeddings(self, texts):
            raise RuntimeError("Embedding network connection error")

    before_fail_rows = store.vector_store.table.to_arrow().to_pylist()
    with pytest.raises(RuntimeError):
        await store.reembed_articles([art_with_ctx], client=FailingClient())
    after_fail_rows = store.vector_store.table.to_arrow().to_pylist()
    assert before_fail_rows == after_fail_rows


def test_lance_vector_store_optimize(tmp_path):
    """LanceVectorStore.optimize compacts fragments and index_articles_batch triggers it."""
    from src.storage.vector_store import LanceVectorStore

    vs = LanceVectorStore(str(tmp_path / "test_opt"))
    records = [
        {
            "canonical_id": f"art_{i}",
            "vector": [0.01 * i] * 1024,
            "language": "uz",
            "status": "active",
            "category": "law",
            "disability_types": "[]",
            "embedding_model_version": "bge-m3-2025-11-18",
        }
        for i in range(5)
    ]
    for r in records:
        vs.upsert_vectors([r])

    stats_before = vs.table.stats()
    assert stats_before["fragment_stats"]["num_fragments"] >= 2
    assert vs.count() == 5

    res = vs.optimize(cleanup_older_than=timedelta(seconds=0))
    assert res["fragments_before"] >= 2
    assert res["fragments_after"] == 1
    assert vs.count() == 5


@pytest.mark.asyncio
async def test_index_articles_batch_triggers_optimize(tmp_path, monkeypatch):
    """index_articles_batch triggers optimize when at least one article is indexed; index_article does not."""
    store = HybridStore(str(tmp_path / "test_spy"))
    client = OpenRouterClient()

    art = CanonicalArticle(
        canonical_id="art_spy",
        metadata=ArticleMetadata(
            law_id="law_spy",
            law_title={"uz": "Qonun", "ru": "Закон"},
            law_number="O'RQ-SPY",
            article_number="1-modda",
            article_title={"uz": "Modda", "ru": "Статья"},
            source_url="https://lex.uz/docs/spy",
            effective_date="2022-01-01",
            last_verified_date="2022-01-01",
            source_hash="sha256:spy",
            category="social_protection",
        ),
        translations={"uz": "Matn", "ru": "Текст"},
    )

    optimize_called = []
    orig_optimize = store.vector_store.optimize

    def spy_optimize(*args, **kwargs):
        optimize_called.append(True)
        return orig_optimize(*args, **kwargs)

    monkeypatch.setattr(store.vector_store, "optimize", spy_optimize)

    # Single index_article must NOT call optimize
    await store.index_article(art, client=client)
    assert len(optimize_called) == 0

    # Batch index MUST call optimize
    await store.index_articles_batch([art], client=client)
    assert len(optimize_called) == 1


@pytest.mark.asyncio
async def test_reembed_script_dry_run(tmp_path, capsys):
    """reembed_context.py --dry-run prints stats without embedding and without making network calls."""
    store_dir = tmp_path / "store_dry_run"
    store = HybridStore(str(store_dir))

    art = CanonicalArticle(
        canonical_id="dry_run_art",
        metadata=ArticleMetadata(
            law_id="law_dry",
            law_title={"uz": "Qonun", "ru": "Закон"},
            law_number="O'RQ-DRY",
            chapter_number="1-bob. Umumiy qoidalar",
            article_number="1-modda",
            article_title={"uz": "Modda", "ru": "Статья"},
            source_url="https://lex.uz/docs/dry",
            effective_date="2022-01-01",
            last_verified_date="2022-01-01",
            source_hash="sha256:dry",
            category="social_protection",
        ),
        translations={"uz": "Sinov uchun qisqa matn.", "ru": "Короткий текст для теста."},
    )
    store.fts_store.upsert_article(art)

    exit_code = await reembed_main(["--store-dir", str(store_dir), "--dry-run"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Dry run summary:" in captured.out
    assert "Units to re-embed: 1" in captured.out
    assert "Total chunks:" in captured.out
    assert "Estimated tokens:" in captured.out



@pytest.mark.asyncio
async def test_russian_texts_are_stored_but_not_embedded_by_default(tmp_path):
    store = HybridStore(str(tmp_path / "ru_store"))
    art = CanonicalArticle(
        canonical_id="ru_skip_art_1",
        metadata=ArticleMetadata(
            law_id="law_3", law_title={"uz": "Qonun 3", "ru": "Закон 3"}, law_number="O'RQ-3", article_number="1-modda",
            article_title={"uz": "Modda", "ru": "Статья"}, source_url="https://lex.uz/docs/3", effective_date="2022-01-01",
            last_verified_date="2022-01-01", source_hash="sha256:ru", category="social_protection",
        ),
        translations={"uz": "Nogironligi bo'lgan shaxslar uchun imtiyozlar belgilanadi.", "ru": "Устанавливаются льготы для лиц с инвалидностью."},
    )
    await store.index_article(art, client=OpenRouterClient())
    rows = store.vector_store.table.search().select(["canonical_id", "language"]).limit(10).to_arrow().to_pylist()
    assert {r["language"] for r in rows if r["canonical_id"] == "ru_skip_art_1"} == {"uz"}
    assert "Устанавливаются" in store.get_article("ru_skip_art_1").get_text("ru")      # the text itself is kept
    assert store.fts_store.bm25_search("льготы инвалидностью", language="ru", top_k=5) == []   # and is not searched
