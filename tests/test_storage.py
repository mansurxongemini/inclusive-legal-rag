import pytest
from pathlib import Path
from src.schema.canonical import CanonicalArticle
from src.storage.hybrid_store import HybridStore
from tests.vector_helpers import vector_rows
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


def test_fts_article_cache_sees_a_write_of_another_process(tmp_path):
    """The corpus build script is a separate process: its writes never pass through the server's cache, so a
    repealed act kept being served as active until someone called clear_article_cache(). The store now notices the
    write (the database files changed) and drops its cache by itself."""
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

    assert server.get_article(cid).metadata.status.value == "repealed"    # no restart, no manual clearing
    assert server.get_articles_batch([cid])[cid].metadata.status.value == "repealed"


from src.schema.canonical import ArticleMetadata
from src.storage.chunking import build_chunks
from scripts.reembed_context import main as reembed_main


@pytest.mark.asyncio
async def test_reembed_articles(tmp_path, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "VECTOR_LANGUAGES", "uz,ru")             # this test is about both languages
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

    orig_rows = vector_rows(store.vector_store)
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

    # 4. Check the new vectors
    new_rows = vector_rows(store.vector_store)
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
        get_query_embeddings = get_embeddings          # questions and units are embedded alike here

    before_fail_rows = vector_rows(store.vector_store)
    with pytest.raises(RuntimeError):
        await store.reembed_articles([art_with_ctx], client=FailingClient())
    after_fail_rows = vector_rows(store.vector_store)
    assert before_fail_rows == after_fail_rows


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
    rows = vector_rows(store.vector_store)
    assert {r["language"] for r in rows if r["canonical_id"] == "ru_skip_art_1"} == {"uz"}
    assert "Устанавливаются" in store.get_article("ru_skip_art_1").get_text("ru")      # the text itself is kept
    assert store.fts_store.bm25_search("льготы инвалидностью", language="ru", top_k=5) == []   # and is not searched


def _three_language_article(canonical_id: str) -> CanonicalArticle:
    from src.schema.canonical import ArticleMetadata

    return CanonicalArticle(
        canonical_id=canonical_id,
        metadata=ArticleMetadata(
            law_id="law_4", law_title={"uz": "Qonun 4"}, law_number="O'RQ-4", article_number="1-modda",
            article_title={"uz": "Modda"}, source_url="https://lex.uz/docs/4", effective_date="2022-01-01",
            last_verified_date="2022-01-01", source_hash="sha256:three", category="social_protection",
        ),
        translations={"uz": "Nogironligi bo'lgan shaxslar uchun imtiyozlar belgilanadi.",
                      "ru": "Устанавливаются льготы для лиц с инвалидностью.",
                      "en": "Benefits are established for persons with disabilities.", "xx": "   "},
    )


def test_only_uzbek_gets_vectors_the_other_texts_are_kept(monkeypatch):
    from src.config import Settings, settings
    from src.storage.hybrid_store import vector_languages

    assert Settings.model_fields["VECTOR_LANGUAGES"].default == "uz"
    art = _three_language_article("langs_rule_1")
    monkeypatch.setattr(settings, "VECTOR_LANGUAGES", "uz")
    assert vector_languages(art) == ["uz"]                            # ru and en are kept in the article, never embedded
    assert art.translations["ru"] and art.translations["en"]
    monkeypatch.setattr(settings, "VECTOR_LANGUAGES", "uz, RU")
    assert vector_languages(art) == ["uz", "ru"]                      # "xx" has no text and is not listed
    monkeypatch.setattr(settings, "VECTOR_LANGUAGES", " ")
    assert vector_languages(art) == ["uz"]                            # a blank setting is the default, not "no vectors"


@pytest.mark.asyncio
async def test_single_and_batch_indexing_make_the_same_vector_languages(tmp_path, monkeypatch):
    """index_article embedded every translation, the batch and re-embedding paths only a fixed uz/ru pair: a unit had
    other vectors depending on which importer had written it."""
    from src.config import settings

    monkeypatch.setattr(settings, "VECTOR_LANGUAGES", "uz")
    art = _three_language_article("langs_same_1")
    single, batch = HybridStore(str(tmp_path / "single")), HybridStore(str(tmp_path / "batch"))
    await single.index_article(art, client=OpenRouterClient())
    await batch.index_articles_batch([art], client=OpenRouterClient())

    def languages(store):
        rows = vector_rows(store.vector_store)
        return {r["language"] for r in rows if r["canonical_id"] == "langs_same_1"}

    assert languages(single) == languages(batch) == {"uz"}


def test_vector_store_writes_and_searches_only_the_vector_languages(tmp_path, monkeypatch):
    from src.config import settings
    from src.storage.vector_store import VectorStore

    store = VectorStore(str(tmp_path))
    vec = [0.1] * settings.EMBEDDING_DIMENSION

    def rec(cid, language):
        return {"canonical_id": cid, "vector": vec, "language": language, "status": "active", "category": "c",
                "disability_types": "[]", "embedding_model_version": "v"}

    def found():
        return {r["canonical_id"] for r in store.search_vector(vec, top_k=10)}

    monkeypatch.setattr(settings, "VECTOR_LANGUAGES", "uz")
    store.upsert_vectors([rec("a_art_1", "uz"), rec("b_art_1", "ru")])
    assert store.count() == 1 and found() == {"a_art_1"}              # the Russian record is not stored
    store.upsert_vectors([rec("a_art_1", "ru")])                      # only foreign records: nothing is written or wiped
    assert store.count() == 1 and found() == {"a_art_1"}

    # a Russian row that is already in the table (a store restored from an old backup) is not searched
    monkeypatch.setattr(settings, "VECTOR_LANGUAGES", "uz,ru")
    store.upsert_vectors([rec("d_art_1", "ru")])
    assert found() == {"a_art_1", "d_art_1"}
    monkeypatch.setattr(settings, "VECTOR_LANGUAGES", "uz")
    assert found() == {"a_art_1"}




def test_upserting_a_unit_replaces_its_rows_and_compacting_keeps_them(tmp_path):
    from src.config import settings
    from src.storage.vector_store import VectorStore

    store = VectorStore(str(tmp_path))
    vec = [0.01] * settings.EMBEDDING_DIMENSION

    def rec(cid, chunk_index=0):
        return {"canonical_id": cid, "vector": vec, "language": "uz", "status": "active", "category": "c",
                "disability_types": "[]", "embedding_model_version": "v", "chunk_index": chunk_index}

    for i in range(6):
        store.upsert_vectors([rec(f"a_{i}"), rec("same", 0), rec("same", 1)])
    assert store.count() == 6 + 2                                   # "same" is replaced each time, never duplicated
    assert store.canonical_ids() == {f"a_{i}" for i in range(6)} | {"same"}

    store.delete_by_canonical_id("hp_ru_2966_1")                    # a unit that has no vectors: nothing happens
    store.delete_many(["hp_ru_2966_2", "hp_ru_2966_3"])
    assert store.count() == 8
    store.delete_many([f"a_{i}" for i in range(5)])
    freed = store.compact()
    assert store.count() == 3 and freed["bytes_after"] <= freed["bytes_before"]
    assert store.models() == {"v": 3} and store.set_model_version("w") == 3 and store.models() == {"w": 3}
    assert store.search_vector(vec, top_k=5)[0]["canonical_id"] in {"a_5", "same"}


def test_the_units_of_one_act_are_read_through_an_index(tmp_path):
    """law_units / law_units_full ran a full scan of the table, parsing the JSON of every unit (177 ms of CPU per call)."""
    from src.editorial.doc_watch import law_units

    store = HybridStore(str(tmp_path / "idx"))
    plan = " ".join(r[3] for r in store.fts_store._get_connection().execute(
        "EXPLAIN QUERY PLAN SELECT canonical_id FROM articles_metadata "
        "WHERE json_extract(json_data, '$.metadata.law_id') = ?", ("law_x",)))
    assert "USING INDEX idx_articles_law_id" in plan and law_units(store, "law_x") == {}
