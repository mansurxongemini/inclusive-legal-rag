import json
import pytest
from pathlib import Path
from typing import Dict, List, Optional
from src.storage.hybrid_store import HybridStore
from src.retrieval.hybrid_retriever import HybridRetriever, ScoredArticle
from src.retrieval.expansion import expand_cross_references
from src.retrieval.status_filter import apply_status_and_amendment_filter
from src.retrieval.reranker import Reranker, split_windows
from src.retrieval.pipeline import merge_candidates
from src.nlp.query_analyzer import QueryAnalyzer
from src.nlp.query_translator import QueryTranslator
from src.schema.canonical import CanonicalArticle, ArticleMetadata, ArticleStatus
from src.clients.openrouter import OpenRouterClient


@pytest.fixture
async def populated_store(tmp_path):
    store = HybridStore(str(tmp_path / "rag_test_store"))
    client = OpenRouterClient()
    pilot_file = Path("tests/fixtures/synthetic_pilot.json")
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
    assert "synthetic_law_art_15" in top_ids


@pytest.mark.asyncio
async def test_hybrid_retrieval_with_precomputed_vector(populated_store):
    store = populated_store
    client = OpenRouterClient()
    retriever = HybridRetriever(store, client=client)

    analysis = QueryAnalyzer.analyze("Nogironligi bo'lgan shaxslarga tibbiy yordam va dori-darmonlar")
    precomputed = (await client.get_embeddings([analysis.normalized_query]))[0]

    results = await retriever.retrieve(analysis, top_k=5, precomputed_query_vector=precomputed)
    assert len(results) > 0
    top_ids = [r.canonical_id for r in results]
    assert "synthetic_law_art_15" in top_ids


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
    assert "synthetic_law_art_24" in ids_latin
    assert "synthetic_law_art_24" in ids_cyrillic


@pytest.mark.asyncio
async def test_cross_reference_expansion(populated_store):
    store = populated_store
    retriever = HybridRetriever(store)

    # Query for employment: Article 36 has cross-ref to labor code article 425
    analysis = QueryAnalyzer.analyze("nogironlarni ishga qabul qilish kvotasi va mehnat huquqi")
    candidates = await retriever.retrieve(analysis, top_k=3)
    
    candidate_ids = [c.canonical_id for c in candidates]
    assert "synthetic_law_art_36" in candidate_ids

    # Run expansion
    expanded = expand_cross_references(candidates, store, max_extra=2)
    expanded_ids = [e.canonical_id for e in expanded]
    
    # synthetic_labor_art_425 should be expanded!
    assert "synthetic_labor_art_425" in expanded_ids


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
        assert "synthetic_law_art_15" in updated_ids


@pytest.mark.asyncio
async def test_a_repealed_unit_is_never_an_answer_source(populated_store):
    from src.retrieval.hybrid_retriever import ScoredArticle
    store = populated_store
    repealed = [a.canonical_id for a in store.list_articles(limit=100) if a.metadata.status.value == "repealed"]
    assert repealed
    candidates = [ScoredArticle(canonical_id=repealed[0], rrf_score=0.9)]
    updated, warnings = apply_status_and_amendment_filter(candidates, store)
    assert repealed[0] not in [u.canonical_id for u in updated]                 # dropped
    assert [w["canonical_id"] for w in warnings] == [repealed[0]]                # but reported
    assert "synthetic_law_art_15" in [u.canonical_id for u in updated]          # its current replacement is used


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
    assert "synthetic_law_art_28" in final_ids


def test_split_windows():
    # 1. Short text -> 1 window
    short = "Nogironligi bo'lgan shaxslarning huquqlari to'g'risida."
    res_short = split_windows(short)
    assert len(res_short) == 1
    assert res_short[0] == short

    # Empty text -> []
    assert split_windows("") == []
    assert split_windows("   \n\t  ") == []

    # 2. A 3000-char text -> several windows, each <= 700 chars, consecutive windows overlap,
    # no window starts or ends in the middle of a word when spaces exist, at most 8 windows.
    sample_words = [
        "O'zbekiston", "Respublikasining", "nogironligi", "bo'lgan", "shaxslar",
        "huquqlari", "to'g'risidagi", "qonunchiligi", "jamiyat", "hayotida",
        "teng", "ishtirok", "etish", "kafolatlari", "tibbiy", "ijtimoiy",
        "reabilitatsiya", "vositalari", "va", "maxsus", "shart-sharoitlar"
    ]
    parts: List[str] = []
    curr_len = 0
    idx = 0
    while curr_len < 3000:
        w = sample_words[idx % len(sample_words)]
        parts.append(w)
        curr_len += len(w) + 1
        idx += 1
    long_text = " ".join(parts)
    assert len(long_text) >= 3000

    windows = split_windows(long_text)

    # Several windows
    assert len(windows) > 1
    # At most 8 windows
    assert len(windows) <= 8

    # Each <= 700 chars
    for w in windows:
        assert len(w) <= 700
        assert len(w) > 0

    # Consecutive windows overlap
    for i in range(len(windows) - 1):
        w1 = windows[i]
        w2 = windows[i + 1]
        pos1 = long_text.find(w1)
        pos2 = long_text.find(w2, pos1)
        end1 = pos1 + len(w1)
        assert pos2 < end1, f"Windows {i} and {i+1} do not overlap (pos2={pos2}, end1={end1})"

    # No window starts or ends in the middle of a word when spaces exist
    for idx_w, w in enumerate(windows):
        pos = long_text.find(w)
        assert pos != -1
        if pos > 0:
            assert long_text[pos - 1].isspace(), f"Window {idx_w} starts mid-word: char before is {repr(long_text[pos - 1])}"
        end_pos = pos + len(w)
        if end_pos < len(long_text):
            assert long_text[end_pos].isspace(), f"Window {idx_w} ends mid-word: char after is {repr(long_text[end_pos])}"


@pytest.mark.asyncio
async def test_reranker_scores_beyond_18_and_sees_text_after_char_600(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "cohere")  # this test is about the cross-encoder path
    # Build 25 candidates and articles.
    # The 22nd candidate (index 21) has a special marker word ONLY after character 1000.
    marker = "MAXSUS_TEST_KALIT_SOZ_UNIQUE"

    articles: Dict[str, CanonicalArticle] = {}
    for i in range(25):
        cid = f"test_art_{i}"
        filler = f"Norma {i} bo'yicha umumiy asosiy qoidalar va belgilangan huquqiy tartiblar haqida batafsil ma'lumot beriladi. " * 15
        if i == 21:
            # 22nd candidate: marker appears ONLY after character 1000
            prefix = filler[:1050]
            suffix = filler[1050:]
            body = f"{prefix} {marker} {suffix}"
            assert body.find(marker) > 1000
        else:
            body = filler

        meta = ArticleMetadata(
            law_id="test_law",
            law_title={"uz": "Sinov Qonuni"},
            law_number="O'RQ-777",
            article_number=f"{i+1}-modda",
            article_title={"uz": f"Sarlavha {i+1}"},
            source_url="https://lex.uz",
            effective_date="2022-01-01",
            last_verified_date="2022-01-01",
            source_hash=f"sha256:hash_{i}",
            status=ArticleStatus.ACTIVE,
            category="disability_rights",
        )
        articles[cid] = CanonicalArticle(
            canonical_id=cid,
            metadata=meta,
            translations={"uz": body},
        )

    # 25 candidates with decreasing initial rrf_score (so index 0 is initially ranked first, index 21 is ranked 22nd)
    candidates = [
        ScoredArticle(canonical_id=f"test_art_{i}", rrf_score=0.5 - (i * 0.01), source_tag="primary")
        for i in range(25)
    ]

    class FakeStore:
        def get_articles_batch(self, cids: List[str]) -> Dict[str, CanonicalArticle]:
            return {c: articles[c] for c in cids if c in articles}

    class StubRerankClient:
        async def rerank_documents(self, query: str, documents: List[str], model: Optional[str] = None, top_n: Optional[int] = None):
            results = []
            for idx, doc in enumerate(documents):
                if marker in doc:
                    results.append({"index": idx, "relevance_score": 0.98})
                else:
                    results.append({"index": idx, "relevance_score": 0.02})
            results.sort(key=lambda x: x["relevance_score"], reverse=True)
            return results[:top_n] if top_n else results

    reranker = Reranker(client=StubRerankClient())
    results = await reranker.rerank(
        query="maxsus qidiruv",
        language="uz",
        candidates=candidates,
        store=FakeStore(),
        top_n=5,
    )

    assert len(results) == 5
    # The 22nd candidate (test_art_21) must be first in the result!
    assert results[0].article.canonical_id == "test_art_21"
    assert results[0].rerank_score == 0.98


def test_merge_candidates():
    c1 = ScoredArticle(
        canonical_id="art_alpha",
        rrf_score=0.04,
        bm25_rank=10,
        vector_rank=25,
        bm25_score=5.0,
        vector_score=0.6,
        source_tag="primary",
    )
    c2 = ScoredArticle(
        canonical_id="art_beta",
        rrf_score=0.03,
        bm25_rank=15,
        vector_rank=30,
        bm25_score=4.0,
        vector_score=0.5,
        source_tag="primary",
    )
    c1_dup = ScoredArticle(
        canonical_id="art_alpha",
        rrf_score=0.05,
        bm25_rank=3,
        vector_rank=40,
        bm25_score=8.5,
        vector_score=0.4,
        source_tag="direct_match",
    )
    c3 = ScoredArticle(
        canonical_id="art_gamma",
        rrf_score=0.01,
        bm25_rank=1,
        vector_rank=2,
        bm25_score=12.0,
        vector_score=0.9,
        source_tag="primary",
    )

    list1 = [c1, c2]
    list2 = [c1_dup, c3]

    # Save state snapshots to verify inputs are not mutated
    c1_snap = c1.model_dump()
    c2_snap = c2.model_dump()
    c1_dup_snap = c1_dup.model_dump()
    c3_snap = c3.model_dump()

    merged = merge_candidates([list1, list2], limit=2)

    # Limit is respected
    assert len(merged) == 2

    # art_alpha present in both lists:
    # rrf_score = 0.04 + 0.05 = 0.09
    # bm25_rank = min(10, 3) = 3
    # vector_rank = min(25, 40) = 25
    # bm25_score = max(5.0, 8.5) = 8.5
    # vector_score = max(0.6, 0.4) = 0.6
    # source_tag = "direct_match"
    top = merged[0]
    assert top.canonical_id == "art_alpha"
    assert round(top.rrf_score, 4) == 0.09
    assert top.bm25_rank == 3
    assert top.vector_rank == 25
    assert top.bm25_score == 8.5
    assert top.vector_score == 0.6
    assert top.source_tag == "direct_match"

    # Input objects are unchanged
    assert c1.model_dump() == c1_snap
    assert c2.model_dump() == c2_snap
    assert c1_dup.model_dump() == c1_dup_snap
    assert c3.model_dump() == c3_snap


@pytest.mark.asyncio
async def test_query_translator_to_uzbek_mock_and_uz():
    # 1. Mock client returns None for any query
    mock_client = OpenRouterClient()
    assert mock_client.is_mock is True

    res_ru = await QueryTranslator.to_uzbek("Каковы права инвалидов?", "ru", mock_client)
    assert res_ru is None

    res_en = await QueryTranslator.to_uzbek("What are disability rights?", "en", mock_client)
    assert res_en is None

    # 2. Language "uz" returns None even with non-mock client
    class NonMockClient:
        is_mock = False
        async def chat_completion(self, messages, temperature=0.0, max_tokens=2000, min_chars=30, reasoning=None, **kwargs):
            return "Nogironlar huquqlari qanday?"

    real_client = NonMockClient()
    res_uz = await QueryTranslator.to_uzbek("Nogironlar huquqlari qanday?", "uz", real_client)
    assert res_uz is None

    # 3. Non-mock client with Russian query returns translated text and caches
    res_translated = await QueryTranslator.to_uzbek("Каковы права инвалидов?", "ru", real_client)
    assert res_translated == "Nogironlar huquqlari qanday?"


@pytest.mark.asyncio
async def test_query_translator_passes_reasoning_and_max_tokens():
    recorded_kwargs = {}

    class RecordingClient:
        is_mock = False

        async def chat_completion(self, **kwargs):
            recorded_kwargs.update(kwargs)
            return "Nogironligi bo'lgan shaxslarning pensiya ta'minoti qanday belgilanadi?"

    client = RecordingClient()
    unique_query = "Kak rasschityvaetsya pensiya dlya invalidov vtoroy gruppy 2026?"
    res = await QueryTranslator.to_uzbek(unique_query, "ru", client)
    assert res == "Nogironligi bo'lgan shaxslarning pensiya ta'minoti qanday belgilanadi?"
    assert recorded_kwargs.get("reasoning") == {"enabled": False}
    assert recorded_kwargs.get("max_tokens") == 300


@pytest.mark.asyncio
async def test_uzbek_normalization_is_skipped_in_mock_mode_and_passes_reasoning_and_max_tokens():
    assert await QueryTranslator.normalize_uzbek("озик овкат ккийим вавчир", OpenRouterClient()) is None   # mock client

    recorded_kwargs = {}

    class RecordingClient:
        is_mock = False

        async def chat_completion(self, **kwargs):
            recorded_kwargs.update(kwargs)
            return "Nogironligi bo'lgan shaxslarning pensiya ta'minoti qanday belgilanadi?"

    unique_query = "Nogironligi bolgan shaxslar pensiyasi qanday hisoblanadi 2026 yilda?"
    res = await QueryTranslator.normalize_uzbek(unique_query, RecordingClient())
    assert res == "Nogironligi bo'lgan shaxslarning pensiya ta'minoti qanday belgilanadi?"
    assert recorded_kwargs.get("reasoning") == {"enabled": False}
    assert recorded_kwargs.get("max_tokens") == 300


@pytest.mark.asyncio
async def test_jev_ranker_rank():
    from src.retrieval.jev_ranker import JevRanker
    from src.retrieval.reranker import RetrievedArticleContext

    class StubClient:
        def __init__(self, return_val):
            self.return_val = return_val

        async def decide(self, state, questions, model=None, timeout=None):
            return self.return_val

    def make_ctx(i):
        meta = ArticleMetadata(
            law_id="test_law",
            law_title={"uz": "Qonun"},
            law_number="O'RQ-100",
            article_number=f"{i}-modda",
            article_title={"uz": f"Modda {i}"},
            source_url="https://lex.uz",
            effective_date="2022-01-01",
            last_verified_date="2022-01-01",
            source_hash=f"sha256:h_{i}",
            status=ArticleStatus.ACTIVE,
            category="disability_rights",
        )
        art = CanonicalArticle(canonical_id=f"art_{i}", metadata=meta, translations={"uz": f"Matn {i}"})
        return RetrievedArticleContext(article=art, final_score=1.0, source_tag="primary")

    contexts = [make_ctx(1), make_ctx(2), make_ctx(3)]
    stub_response = {
        "answers": {
            "best": {"probabilities": {"p1": 0.1, "p2": 0.7, "p3": 0.2}},
            "answerable": {"noul": 0.83},
        },
        "usage": {"cost": 0.0004},
    }
    ranker = JevRanker(client=StubClient(stub_response))
    result = await ranker.rank("test query", contexts)
    assert result is not None
    assert result.order == [1, 2, 0]
    assert result.answerable == 0.83
    assert result.cost == 0.0004
    assert result.probabilities == [0.1, 0.7, 0.2]

    none_ranker = JevRanker(client=StubClient(None))
    assert await none_ranker.rank("test query", contexts) is None


@pytest.mark.asyncio
async def test_jev_ranker_scope():
    from src.retrieval.jev_ranker import JevRanker

    class StubClient:
        def __init__(self, return_val):
            self.return_val = return_val

        async def decide(self, state, questions, model=None, timeout=None):
            return self.return_val

    stub_response = {
        "answers": {
            "scope": {"probabilities": {"in_scope": 0.75}}
        }
    }
    ranker = JevRanker(client=StubClient(stub_response))
    in_scope = await ranker.scope("Qandaydir savol")
    assert in_scope == 0.75

    none_ranker = JevRanker(client=StubClient(None))
    assert await none_ranker.scope("Qandaydir savol") is None


@pytest.mark.asyncio
async def test_reranker_jev_path(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "jev")

    articles: Dict[str, CanonicalArticle] = {}
    for i in range(10):
        cid = f"cand_art_{i}"
        meta = ArticleMetadata(
            law_id="test_law",
            law_title={"uz": "Qonun"},
            law_number="O'RQ-100",
            article_number=f"{i+1}-modda",
            article_title={"uz": f"Modda {i+1}"},
            source_url="https://lex.uz",
            effective_date="2022-01-01",
            last_verified_date="2022-01-01",
            source_hash=f"sha256:h_{i}",
            status=ArticleStatus.ACTIVE,
            category="disability_rights",
        )
        articles[cid] = CanonicalArticle(canonical_id=cid, metadata=meta, translations={"uz": f"Matn {i}"})

    class FakeStore:
        def get_articles_batch(self, cids: List[str]) -> Dict[str, CanonicalArticle]:
            return {c: articles[c] for c in cids if c in articles}

    class StubJevClient:
        is_mock = False

        async def decide(self, state, questions, model=None, timeout=None):
            probs = {f"p{n+1}": 0.01 for n in range(10)}
            probs["p3"] = 0.85
            return {
                "answers": {
                    "best": {"probabilities": probs},
                    "answerable": {"noul": 0.91},
                },
                "usage": {"cost": 0.0005},
            }

    # 1. Without direct_match: 3rd candidate is returned first
    candidates = [
        ScoredArticle(canonical_id=f"cand_art_{i}", rrf_score=0.5 - (i * 0.01), source_tag="primary")
        for i in range(10)
    ]
    reranker = Reranker(client=StubJevClient())
    results = await reranker.rerank(
        query="test query",
        language="uz",
        candidates=candidates,
        store=FakeStore(),
        top_n=3,
    )
    assert len(results) == 3
    assert results[0].article.canonical_id == "cand_art_2"
    assert reranker.last_provider == "jev"
    assert reranker.last_answerable == 0.91

    # 2. With direct_match: direct_match candidate is kept first
    candidates_with_dm = [
        ScoredArticle(
            canonical_id=f"cand_art_{i}",
            rrf_score=0.5 - (i * 0.01),
            source_tag="direct_match" if i == 0 else "primary"
        )
        for i in range(10)
    ]
    reranker_dm = Reranker(client=StubJevClient())
    results_dm = await reranker_dm.rerank(
        query="test query",
        language="uz",
        candidates=candidates_with_dm,
        store=FakeStore(),
        top_n=3,
    )
    assert len(results_dm) == 3
    assert results_dm[0].article.canonical_id == "cand_art_0"
    assert results_dm[1].article.canonical_id == "cand_art_2"
    assert reranker_dm.last_provider == "jev"
    assert reranker_dm.last_answerable == 0.91


@pytest.mark.asyncio
async def test_reranker_fallback_to_cohere(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "jev")

    articles: Dict[str, CanonicalArticle] = {}
    for i in range(10):
        cid = f"fb_art_{i}"
        meta = ArticleMetadata(
            law_id="test_law",
            law_title={"uz": "Qonun"},
            law_number="O'RQ-100",
            article_number=f"{i+1}-modda",
            article_title={"uz": f"Modda {i+1}"},
            source_url="https://lex.uz",
            effective_date="2022-01-01",
            last_verified_date="2022-01-01",
            source_hash=f"sha256:h_{i}",
            status=ArticleStatus.ACTIVE,
            category="disability_rights",
        )
        articles[cid] = CanonicalArticle(canonical_id=cid, metadata=meta, translations={"uz": f"Matn {i}"})

    class FakeStore:
        def get_articles_batch(self, cids: List[str]) -> Dict[str, CanonicalArticle]:
            return {c: articles[c] for c in cids if c in articles}

    class StubFallbackClient:
        is_mock = False

        async def decide(self, state, questions, model=None, timeout=None):
            return None

        async def rerank_documents(self, query, documents, model=None, top_n=None):
            return [{"index": i, "relevance_score": 0.9 - (i * 0.05)} for i in range(len(documents))]

    candidates = [
        ScoredArticle(canonical_id=f"fb_art_{i}", rrf_score=0.5 - (i * 0.01), source_tag="primary")
        for i in range(10)
    ]
    reranker = Reranker(client=StubFallbackClient())
    results = await reranker.rerank(
        query="test fallback",
        language="uz",
        candidates=candidates,
        store=FakeStore(),
        top_n=3,
    )
    assert len(results) == 3
    assert reranker.last_provider == "cohere"


def test_jev_gate_decision(monkeypatch):
    from src.config import settings
    from src.retrieval.relevance_gate import jev_gate_decision

    monkeypatch.setattr(settings, "GATE_JEV_SCOPE_ENABLED", True)
    monkeypatch.setattr(settings, "GATE_JEV_MIN_IN_SCOPE", 0.3)

    # a low scope is refused whatever the answerability: the Traffic and Criminal codes in the corpus answer their
    # questions (0.89-0.96) just like the Convention questions that Jev misjudges
    for answerable in (0.5, 0.95, None):
        d = jev_gate_decision(in_scope=0.1, answerable=answerable, top_probability=None)
        assert d.answerable is False and d.reason == "jev_out_of_scope"

    # in scope: accepted, and the answerability (else the top probability, else 1.0) is the confidence
    d = jev_gate_decision(in_scope=0.8, answerable=0.2, top_probability=None)
    assert d.answerable is True and d.reason == "jev_match" and d.confidence == 0.2
    assert jev_gate_decision(in_scope=0.8, answerable=None, top_probability=0.6).confidence == 0.6
    assert jev_gate_decision(in_scope=None, answerable=None, top_probability=None).answerable is True   # no scope signal

    monkeypatch.setattr(settings, "GATE_JEV_SCOPE_ENABLED", False)
    assert jev_gate_decision(in_scope=0.1, answerable=0.5, top_probability=None).answerable is True


@pytest.mark.asyncio
async def test_openrouter_decide_http_error():
    from src.clients.openrouter import OpenRouterClient

    class FakeResponse:
        status_code = 500
        text = "Internal Server Error"

        def json(self):
            return {}

    class FakeAsyncClient:
        is_closed = False

        async def post(self, url, json=None, timeout=None):
            return FakeResponse()

        async def aclose(self):
            pass

    client = OpenRouterClient()
    client.is_mock = False
    client.api_key = "test_key"
    client.jev_api_key = client.api_key            # decisions go through the Jev client: with one shared key that is the fake
    client.base_url = "https://openrouter.ai/api/v1"
    client._http_client = FakeAsyncClient()

    decide_res = await client.decide(state="test state", questions={"q": {"type": "choice"}})
    assert decide_res is None





@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["rrf", "none"])
async def test_rrf_provider_never_calls_a_rerank_model(monkeypatch, provider):
    from types import SimpleNamespace
    from src.config import settings

    monkeypatch.setattr(settings, "RERANK_PROVIDER", provider)
    with open("data/pilot_laws/law_disability_2020.json", encoding="utf-8") as f:
        art = CanonicalArticle.model_validate(json.load(f)[0])
    arts = {f"id{i}": art.model_copy(update={"canonical_id": f"id{i}"}) for i in range(12)}

    class NoModelClient:
        is_mock = False
        async def rerank_documents(self, *a, **kw):
            raise AssertionError("rerank endpoint must not be called")
        async def decide(self, *a, **kw):
            raise AssertionError("Jev must not be called")

    store = SimpleNamespace(get_articles_batch=lambda ids: {i: arts[i] for i in ids if i in arts})
    cands = [ScoredArticle(canonical_id=f"id{i}", rrf_score=1.0 - i / 100, source_tag="rrf") for i in range(12)]
    reranker = Reranker(client=NoModelClient())
    out = await reranker.rerank("savol", "uz", cands, store, top_n=5, use_model=True)
    assert [c.article.canonical_id for c in out] == [f"id{i}" for i in range(5)]
    assert reranker.last_provider == "rrf"


def test_a_unit_that_leads_one_list_is_lifted_into_the_reranker_window():
    from src.retrieval.hybrid_retriever import ScoredArticle, lift_leaders

    scored = [ScoredArticle(canonical_id=f"u{i}", rrf_score=1.0 - i * 0.01) for i in range(40)]
    lift_leaders(scored, {"u35", "u2"}, anchor_position=12)
    order = [s.canonical_id for s in scored]
    assert order.index("u35") <= 13                       # lifted from the 36th place to the anchor
    assert order[:11] == [f"u{i}" for i in range(11)]     # the strong head is untouched
    assert order.index("u2") == 2                         # a leader that is already high stays where it was
    scored2 = [ScoredArticle(canonical_id=f"v{i}", rrf_score=1.0 - i * 0.01) for i in range(5)]
    lift_leaders(scored2, {"v4"}, anchor_position=12)     # a pool smaller than the anchor is left alone
    assert [s.canonical_id for s in scored2] == [f"v{i}" for i in range(5)]
