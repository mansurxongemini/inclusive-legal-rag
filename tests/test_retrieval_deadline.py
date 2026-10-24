"""
A provider that hangs (no answer, no error) must not hold a request: retrieval has a deadline, after which the question
is searched by full-text search with no model call. Found by eval/check_server.py (a fake provider that never answers
kept POST /api/v1/query open for more than two minutes).
"""
import asyncio
from types import SimpleNamespace

import pytest

from src.nlp.query_analyzer import QueryAnalyzer
from src.nlp.query_translator import QueryTranslator
from src.retrieval import pipeline


@pytest.mark.asyncio
async def test_a_hanging_retrieval_falls_back_to_full_text_search(monkeypatch):
    calls = []

    async def fake_retrieve(**kwargs):
        calls.append(kwargs)
        if kwargs.get("use_llm", True):
            await asyncio.sleep(30)                      # the provider never answers
        return pipeline.RetrievalResult(contexts=[], signals={})

    monkeypatch.setattr(pipeline, "retrieve_contexts", fake_retrieve)
    res = await pipeline.retrieve_within(0.05, analysis=None, store=None, client=None, query_vector=[0.1], use_vector=True)
    assert res.signals["retrieval_timeout"] is True
    assert len(calls) == 2
    assert calls[1]["use_llm"] is False and calls[1]["use_vector"] is False and calls[1]["query_vector"] is None


@pytest.mark.asyncio
async def test_a_retrieval_in_time_is_returned_as_is(monkeypatch):
    async def fake_retrieve(**kwargs):
        return pipeline.RetrievalResult(contexts=[], signals={"ok": 1})

    monkeypatch.setattr(pipeline, "retrieve_contexts", fake_retrieve)
    res = await pipeline.retrieve_within(5, analysis=None)
    assert res.signals == {"ok": 1}


@pytest.mark.asyncio
async def test_the_fallback_makes_no_model_call(monkeypatch):
    async def forbidden(*a, **k):
        raise AssertionError("no model call is allowed in the fallback")

    for name in ("to_uzbek", "normalize_uzbek", "legal_subquestions"):
        monkeypatch.setattr(QueryTranslator, name, forbidden)
    client = SimpleNamespace(is_mock=False, get_embeddings=forbidden, chat_completion=forbidden)
    from src.api.app import get_store
    res = await pipeline.retrieve_contexts(
        analysis=QueryAnalyzer.analyze("Какой отпуск положен работнику с инвалидностью I группы при трудовом увечье?"),
        store=get_store(), client=client, top_k=10, max_extra=2, rerank_top_n=5, use_vector=False, use_llm=False)
    assert res.signals["rerank_provider"] != "jev"
