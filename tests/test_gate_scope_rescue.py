"""
When the model ranker fails (a provider error), the scope judgement already made is kept: a question the judge puts in
scope is not refused by the lexical gate. Gold item en06 (an English question about appealing a TIEK decision) was
refused that way once a transient error hit the ranker call: the lexical gate finds no English words in Uzbek units.
"""
from types import SimpleNamespace

import pytest

from src.api.app import get_store
from src.config import settings
from src.nlp.query_analyzer import QueryAnalyzer
from src.nlp.query_translator import QueryTranslator
from src.retrieval import pipeline
from src.retrieval.relevance_gate import GateDecision


async def _run(monkeypatch, in_scope, lexical_reason="low_relevance"):
    async def no_rewrite(*a, **k):
        return None

    async def scope(self, question):
        return in_scope

    async def rerank_fails_over_to_rrf(self, query, language, candidates, store, top_n, **kw):
        self.last_provider = "rrf"                       # what Reranker reports when the model ranker gave nothing
        arts = store.get_articles_batch([c.canonical_id for c in candidates[:top_n]])
        return [pipeline.RetrievedArticleContext(article=arts[c.canonical_id], final_score=c.rrf_score,
                                                 source_tag="primary") for c in candidates[:top_n] if c.canonical_id in arts]

    for name in ("to_uzbek", "normalize_uzbek", "legal_subquestions"):
        monkeypatch.setattr(QueryTranslator, name, no_rewrite)
    monkeypatch.setattr(pipeline.JevRanker, "scope", scope)
    monkeypatch.setattr(pipeline.Reranker, "rerank", rerank_fails_over_to_rrf)
    monkeypatch.setattr(pipeline.RelevanceGate, "assess", lambda self, **k: GateDecision(False, lexical_reason, 0.1))
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "jev")
    return await pipeline.retrieve_contexts(
        analysis=QueryAnalyzer.analyze("How can I appeal the decision of the medical and social expert commission?"),
        store=get_store(), client=SimpleNamespace(is_mock=False), top_k=10, max_extra=2, rerank_top_n=5, use_vector=False)


@pytest.mark.asyncio
async def test_a_question_in_scope_is_answered_when_the_ranker_failed(monkeypatch):
    res = await _run(monkeypatch, 1.0)
    assert res.decision.answerable and res.decision.reason == "scope_rescue" and res.contexts


@pytest.mark.asyncio
async def test_out_of_scope_is_still_refused_and_an_unsure_scope_keeps_the_lexical_gate(monkeypatch):
    res = await _run(monkeypatch, 0.05)
    assert not res.decision.answerable and res.decision.reason == "jev_out_of_scope" and res.contexts == []
    res = await _run(monkeypatch, 0.5)
    assert not res.decision.answerable and res.decision.reason == "low_relevance"


@pytest.mark.asyncio
async def test_a_cross_encoder_refusal_is_not_overridden(monkeypatch):
    # the cross-encoder judged the units irrelevant: the scope judge (topic only) must not overrule that
    res = await _run(monkeypatch, 1.0, lexical_reason="low_reranker_score")
    assert not res.decision.answerable and res.decision.reason == "low_reranker_score"
