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
    pilot_file = Path("data/pilot_laws/law_disability_2020.json")
    await store.seed_from_file(str(pilot_file), client=client)

    assert store.count() >= 8

    # Fetch specific article
    art15 = store.get_article("law_disability_2020_art_15")
    assert art15 is not None
    assert art15.canonical_id == "law_disability_2020_art_15"
    assert "tibbiy yordam" in art15.get_text("uz").lower()

    # FTS search
    fts_results = store.fts_store.bm25_search("tibbiy yordam", language="uz", top_k=5)
    assert len(fts_results) > 0
    found_ids = [r["canonical_id"] for r in fts_results]
    assert "law_disability_2020_art_15" in found_ids

    # Vector search
    query_vec = (await client.get_embeddings(["Nogironlarga tibbiy xizmat va dori-darmonlar"]))[0]
    vec_results = store.vector_store.search_vector(query_vec, top_k=5, language="uz")
    assert len(vec_results) > 0

    # Delete test
    old_sample = store.get_article("law_disability_old_sample_art_10")
    assert old_sample is not None
    store.delete_article("law_disability_old_sample_art_10")
    assert store.get_article("law_disability_old_sample_art_10") is None
