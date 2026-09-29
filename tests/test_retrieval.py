import pytest
from pathlib import Path
from src.storage.hybrid_store import HybridStore
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.expansion import expand_cross_references
from src.retrieval.status_filter import apply_status_and_amendment_filter
from src.retrieval.reranker import Reranker
from src.nlp.query_analyzer import QueryAnalyzer
from src.clients.openrouter import OpenRouterClient


@pytest.fixture
async def populated_store(tmp_path):
    store = HybridStore(str(tmp_path / "rag_test_store"))
    client = OpenRouterClient()
    pilot_file = Path("data/pilot_laws/law_disability_2020.json")
    await store.seed_from_file(str(pilot_file), client=client)
    return store


@pytest.mark.asyncio
async def test_hybrid_retrieval_latin(populated_store):
    store = populated_store
    retriever = HybridRetriever(store)
    
    # Query in Latin
    analysis = QueryAnalyzer.analyze("Nogironligi bo'lgan shaxslarga tibbiy yordam va dori-darmonlar")
    results = await retriever.retrieve(analysis, top_k=5)
    
    assert len(results) > 0
    top_ids = [r.canonical_id for r in results]
    assert "law_disability_2020_art_15" in top_ids


@pytest.mark.asyncio
async def test_script_invariance_cyrillic_and_latin(populated_store):
    store = populated_store
    retriever = HybridRetriever(store)

    # 1. Latin query
    q_latin = "Nogironlarning transportdan foydalanishi va avtoturargoh imtiyozlari"
    analysis_latin = QueryAnalyzer.analyze(q_latin)
    res_latin = await retriever.retrieve(analysis_latin, top_k=5)
    ids_latin = [r.canonical_id for r in res_latin]

    # 2. Same query in Cyrillic
    q_cyrillic = "Ногиронларнинг транспортдан фойдаланиши ва автотураргоҳ имтиёзлари"
    analysis_cyrillic = QueryAnalyzer.analyze(q_cyrillic)
    res_cyrillic = await retriever.retrieve(analysis_cyrillic, top_k=5)
    ids_cyrillic = [r.canonical_id for r in res_cyrillic]

    # Both must find Article 24 (Transport)
    assert "law_disability_2020_art_24" in ids_latin
    assert "law_disability_2020_art_24" in ids_cyrillic


@pytest.mark.asyncio
async def test_cross_reference_expansion(populated_store):
    store = populated_store
    retriever = HybridRetriever(store)

    # Query for employment: Article 36 has cross-ref to labor code article 425
    analysis = QueryAnalyzer.analyze("nogironlarni ishga qabul qilish kvotasi va mehnat huquqi")
    candidates = await retriever.retrieve(analysis, top_k=3)
    
    candidate_ids = [c.canonical_id for c in candidates]
    assert "law_disability_2020_art_36" in candidate_ids

    # Run expansion
    expanded = expand_cross_references(candidates, store, max_extra=2)
    expanded_ids = [e.canonical_id for e in expanded]
    
    # law_labor_code_art_425 should be expanded!
    assert "law_labor_code_art_425" in expanded_ids


@pytest.mark.asyncio
async def test_status_filter_and_repealed_handling(populated_store):
    store = populated_store
    retriever = HybridRetriever(store)

    # Directly retrieve old sample repealed article
    analysis = QueryAnalyzer.analyze("TMEK tekshiruvi eski tartib")
    candidates = await retriever.retrieve(analysis, top_k=5)

    updated, warnings = apply_status_and_amendment_filter(candidates, store)
    updated_ids = [u.canonical_id for u in updated]

    # If old repealed sample is matched, its replacement art_15 must be pulled in
    if any(w["status"] == "repealed" for w in warnings):
        assert "law_disability_2020_art_15" in updated_ids


@pytest.mark.asyncio
async def test_reranker_end_to_end(populated_store):
    store = populated_store
    retriever = HybridRetriever(store)
    reranker = Reranker()

    analysis = QueryAnalyzer.analyze("Oliy o'quv yurtlariga kirishda nogironlar uchun imtiyozlar bormi?")
    candidates = await retriever.retrieve(analysis, top_k=5)
    expanded = expand_cross_references(candidates, store, max_extra=2)
    filtered, _ = apply_status_and_amendment_filter(expanded, store)

    final_contexts = await reranker.rerank(
        query=analysis.normalized_query,
        language=analysis.detected_language,
        candidates=filtered,
        store=store,
        top_n=3
    )

    assert len(final_contexts) <= 3
    final_ids = [ctx.article.canonical_id for ctx in final_contexts]
    # Article 28 is education/admission quota
    assert "law_disability_2020_art_28" in final_ids
