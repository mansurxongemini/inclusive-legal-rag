from unittest.mock import MagicMock
import pytest

from src.evaluation.retrieval_eval import ItemResult, RetrievalEvaluator, normalize_law_number
from src.retrieval.pipeline import RetrievalResult
from src.retrieval.reranker import RetrievedArticleContext
from src.retrieval.hybrid_retriever import ScoredArticle
from src.schema.canonical import ArticleMetadata, ArticleStatus, CanonicalArticle


def _make_article(canonical_id: str, law_number: str) -> CanonicalArticle:
    meta = ArticleMetadata(
        law_id="dummy_law",
        law_title={"uz": "Qonun", "ru": "Закон", "en": "Law"},
        law_number=law_number,
        article_number="1-modda",
        article_title={"uz": "Modda", "ru": "Статья", "en": "Article"},
        source_url="https://lex.uz",
        effective_date="2024-01-01",
        last_verified_date="2024-01-01",
        source_hash="abcd1234abcd",
        status=ArticleStatus.ACTIVE,
        category="social_protection",
    )
    return CanonicalArticle(
        canonical_id=canonical_id,
        translations={"uz": "Matn", "ru": "Текст", "en": "Text"},
        metadata=meta,
    )


def test_normalize_law_number_apostrophes_and_spacing():
    # Various apostrophes
    assert normalize_law_number("O'RQ-641") == "O'RQ-641"
    assert normalize_law_number("OʻRQ-641") == "O'RQ-641"
    assert normalize_law_number("OʼRQ-641") == "O'RQ-641"
    assert normalize_law_number("O‘RQ-641") == "O'RQ-641"
    assert normalize_law_number("O`RQ-641") == "O'RQ-641"
    assert normalize_law_number("O\u02bbRQ-641") == "O'RQ-641"
    assert normalize_law_number("O\u02bcRQ-641") == "O'RQ-641"

    # Spacing and lowercase
    assert normalize_law_number("  vmq - 313  ") == "VMQ-313"
    assert normalize_law_number("pq-266") == "PQ-266"
    assert normalize_law_number("PF - 115") == "PF-115"
    assert normalize_law_number("O'RQ  -  641") == "O'RQ-641"

    # Empty and None
    assert normalize_law_number("") == ""
    assert normalize_law_number(None) == ""


@pytest.mark.asyncio
async def test_run_item_hit_by_expected_law_numbers(monkeypatch):
    store = MagicMock()
    evaluator = RetrievalEvaluator(store=store, client=MagicMock())

    art1 = _make_article("doc1_art1", "OʻRQ-641")
    art2 = _make_article("doc2_art1", "VMQ-313")

    ctx1 = RetrievedArticleContext(article=art1, rerank_score=0.9, final_score=0.9, original_rank=1, source_tag="hybrid")
    ctx2 = RetrievedArticleContext(article=art2, rerank_score=0.8, final_score=0.8, original_rank=2, source_tag="hybrid")

    fake_result = RetrievalResult(
        contexts=[ctx1, ctx2],
        candidates=[
            ScoredArticle(canonical_id="doc1_art1", rrf_score=0.5, vector_score=0.85),
            ScoredArticle(canonical_id="doc2_art1", rrf_score=0.4, vector_score=0.75),
        ],
    )

    async def fake_retrieve(*args, **kwargs):
        return fake_result

    monkeypatch.setattr("src.evaluation.retrieval_eval.retrieve_contexts", fake_retrieve)

    # Item specifying expected_law_numbers matching the first context
    item = {
        "id": "p001",
        "question": "Nogironligi bo'lgan shaxslar huquqlari qaysi qonunda belgilangan?",
        "language": "uz",
        "expected_ids": [],
        "expected_law_numbers": ["O'RQ-641"],
    }

    res = await evaluator.run_item(item)
    assert res.first_hit_rank == 1
    assert res.expected_law_numbers == ["O'RQ-641"]

    # Item specifying second act as hit
    item2 = {
        "id": "p002",
        "question": "Qaror bo'yicha imtiyoz?",
        "language": "uz",
        "expected_ids": [],
        "expected_law_numbers": ["VMQ-313"],
    }
    res2 = await evaluator.run_item(item2)
    assert res2.first_hit_rank == 2

    # Item where law number does not match
    item3 = {
        "id": "p003",
        "question": "Boshqa qonun?",
        "language": "uz",
        "expected_ids": [],
        "expected_law_numbers": ["PQ-999"],
    }
    res3 = await evaluator.run_item(item3)
    assert res3.first_hit_rank is None


@pytest.mark.asyncio
async def test_run_item_pool_hit_with_refusal(monkeypatch):
    art1 = _make_article("doc1_art1", "PQ-266")
    store = MagicMock()
    store.get_articles_batch.return_value = {"doc1_art1": art1}
    evaluator = RetrievalEvaluator(store=store, client=MagicMock())

    from src.retrieval.relevance_gate import GateDecision

    fake_result = RetrievalResult(
        contexts=[],
        candidates=[
            ScoredArticle(canonical_id="doc1_art1", rrf_score=0.5, vector_score=0.82),
        ],
        decision=GateDecision(answerable=False, confidence=0.3, reason="Low score"),
    )

    async def fake_retrieve(*args, **kwargs):
        return fake_result

    monkeypatch.setattr("src.evaluation.retrieval_eval.retrieve_contexts", fake_retrieve)

    item = {
        "id": "p004",
        "question": "Qulay muhit yaratish qarori qaysi?",
        "language": "uz",
        "expected_ids": [],
        "expected_law_numbers": ["PQ-266"],
    }

    res = await evaluator.run_item(item)
    assert res.refused is True
    assert res.pool_rank == 1
    assert res.first_hit_rank == 1


def test_summarize_coverage_gaps():
    results = [
        ItemResult(
            id="p001",
            question="Mehnat kodeksida nogironlik kafolatlari",
            language="uz",
            out_of_scope=False,
            expected_ids=[],
            returned_ids=[],
            first_hit_rank=None,
            refused=False,
            gate_reason="",
            best_vector_score=None,
            latency_ms=10.0,
            expected_law_numbers=["O'RQ-798"],
            category="labor",
        ),
        ItemResult(
            id="p002",
            question="Nogironlik to'g'risidagi qonun",
            language="uz",
            out_of_scope=False,
            expected_ids=[],
            returned_ids=["doc1_art1"],
            first_hit_rank=1,
            refused=False,
            gate_reason="",
            best_vector_score=None,
            latency_ms=10.0,
            expected_law_numbers=["O'RQ-641"],
            category="general",
        ),
        ItemResult(
            id="p003",
            question="Chet el qonuni",
            language="uz",
            out_of_scope=True,
            expected_ids=[],
            returned_ids=[],
            first_hit_rank=None,
            refused=True,
            gate_reason="out",
            best_vector_score=None,
            latency_ms=10.0,
            expected_law_numbers=["UNKNOWN-001"],
            category="other",
        ),
    ]

    raw_items = [
        {"id": "p001", "question": "Mehnat kodeksida nogironlik kafolatlari", "expected_law_numbers": ["O'RQ-798"], "note": "Yangi Mehnat kodeksi"},
        {"id": "p002", "question": "Nogironlik to'g'risidagi qonun", "expected_law_numbers": ["O'RQ-641"], "note": "Asosiy qonun"},
        {"id": "p003", "question": "Chet el qonuni", "expected_law_numbers": ["UNKNOWN-001"], "out_of_scope": True, "note": "Tashqi"},
    ]

    # Store only contains O'RQ-641
    store_acts = ({"O'RQ-641"}, set())

    rep = RetrievalEvaluator.summarize(results, store_acts=store_acts, raw_items=raw_items)

    assert rep.coverage_gap_count == 1
    assert len(rep.coverage_gaps) == 1
    assert rep.coverage_gaps[0]["id"] == "p001"
    assert rep.coverage_gaps[0]["expected_law_numbers"] == ["O'RQ-798"]
    assert rep.coverage_gaps[0]["note"] == "Yangi Mehnat kodeksi"



def test_code_without_number_matches_by_lex_document_id():
    """Codes have no number on Lex.uz: an empty law number must match nothing, the document id must match."""
    from types import SimpleNamespace
    from src.evaluation.retrieval_eval import lex_doc_key, unit_matches

    assert lex_doc_key("https://lex.uz/uz/docs/-6257288#-6266772") == "6257288"
    assert lex_doc_key("-6257288") == lex_doc_key("6257288") == "6257288"     # Latin and Cyrillic editions
    item = {"expected_law_numbers": [""], "expected_lex_ids": ["-6257288"]}
    labor = SimpleNamespace(metadata=SimpleNamespace(law_number="O'RQ-798", source_url="https://lex.uz/docs/6257288#x"))
    other = SimpleNamespace(metadata=SimpleNamespace(law_number="", source_url="https://lex.uz/uz/docs/-111"))
    assert unit_matches(item, "labor_code_2022_art_161", labor)
    assert not unit_matches(item, "criminal_code_art_1", other)
    assert not unit_matches({"expected_law_numbers": [""]}, "x", other)


def test_coverage_gap_uses_lex_document_ids():
    from src.evaluation.retrieval_eval import ItemResult, RetrievalEvaluator
    r = ItemResult(id="p1", question="q", language="uz", out_of_scope=False, expected_ids=[], returned_ids=[],
                   first_hit_rank=None, refused=False, gate_reason="", best_vector_score=None, latency_ms=1.0)
    raw = [{"id": "p1", "expected_law_numbers": [""], "expected_lex_ids": ["-6257288"]}]
    assert RetrievalEvaluator.summarize([r], store_acts=(set(), {"6257288"}), raw_items=raw).coverage_gap_count == 0
    assert RetrievalEvaluator.summarize([r], store_acts=(set(), {"1"}), raw_items=raw).coverage_gap_count == 1


def test_lex_id_avoids_law_number_collision():
    """When expected_lex_ids is present, same law number from another year is NOT a hit."""
    from types import SimpleNamespace
    from src.evaluation.retrieval_eval import unit_matches

    # Item expects 2024 edition of VMQ-46 (-6779571)
    item = {
        "expected_law_numbers": ["VMQ-46"],
        "expected_lex_ids": ["-6779571"],
    }

    # Wrong year act sharing the same number VMQ-46 (e.g. -261518 from 2008)
    wrong_year_art = SimpleNamespace(
        metadata=SimpleNamespace(
            law_number="VMQ-46",
            source_url="https://lex.uz/uz/docs/-261518",
        )
    )
    # Correct year act
    correct_art = SimpleNamespace(
        metadata=SimpleNamespace(
            law_number="VMQ-46",
            source_url="https://lex.uz/uz/docs/-6779571",
        )
    )

    # Collision must NOT match
    assert not unit_matches(item, "other_vmq_46_art_1", wrong_year_art)
    # Correct act matches
    assert unit_matches(item, "correct_vmq_46_art_1", correct_art)


def test_law_number_fallback_when_no_lex_ids():
    """When expected_lex_ids is absent/empty, law number fallback works as expected."""
    from types import SimpleNamespace
    from src.evaluation.retrieval_eval import unit_matches

    item = {
        "expected_law_numbers": ["VMQ-46"],
        "expected_lex_ids": [],
    }
    art_vmq46 = SimpleNamespace(
        metadata=SimpleNamespace(
            law_number="VMQ-46",
            source_url="https://lex.uz/uz/docs/-261518",
        )
    )
    art_other = SimpleNamespace(
        metadata=SimpleNamespace(
            law_number="VMQ-99",
            source_url="https://lex.uz/uz/docs/-999999",
        )
    )

    assert unit_matches(item, "art_1", art_vmq46)
    assert not unit_matches(item, "art_2", art_other)

