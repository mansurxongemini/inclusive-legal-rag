"""Fallback reranking and scope check on the generation provider when Jev is unavailable."""
import pytest

from src.config import settings
from src.retrieval.jev_ranker import JevRanker
from src.retrieval.llm_ranker import LlmRanker
from src.retrieval.reranker import RetrievedArticleContext
from src.schema.canonical import CanonicalArticle


def _ctx(i):
    art = CanonicalArticle(
        canonical_id=f"u_{i}",
        metadata={"law_id": "l", "law_title": {"uz": "Qonun"}, "law_number": "Q-1", "article_number": f"{i}-band",
                  "article_title": {"uz": f"Band {i}"}, "source_url": "https://lex.uz/docs/1",
                  "effective_date": "2024-01-01", "last_verified_date": "2026-10-01", "source_hash": "sha256:x",
                  "category": "social_protection"},
        translations={"uz": f"{i}-band matni. Nafaqa miqdori {i} baravar."},
    )
    return RetrievedArticleContext(article=art, final_score=1.0 - i * 0.01, source_tag="primary")


class Client:
    is_mock = False

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def decide(self, state, questions, model=None, timeout=None):
        return None                                           # Jev is unavailable

    async def chat_completion(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.mark.asyncio
async def test_the_models_picks_come_first_and_get_jev_like_probabilities():
    client = Client('Javob: {"best": [3, 1, 99, 3], "answerable": 0.9}')
    result = await LlmRanker(client).rank("Nafaqa qancha?", [_ctx(i) for i in range(5)])
    assert result.order == [2, 0, 1, 3, 4]                     # picks first (bad and repeated numbers ignored), the rest as they were
    assert result.probabilities[2] == 0.50 and result.probabilities[0] == 0.20 and result.probabilities[4] == 0.001
    assert result.answerable == pytest.approx(0.9)
    sent = client.calls[0]
    assert "[1]" in sent[0][1]["content"] and sent[1]["light"] is True


@pytest.mark.asyncio
async def test_unusable_replies_give_no_ranking_instead_of_an_invented_one():
    for reply in ("not json", '{"answerable": 0.9}', RuntimeError("down")):
        assert await LlmRanker(Client(reply)).rank("q", [_ctx(1), _ctx(2)]) is None


@pytest.mark.asyncio
async def test_no_passage_answers_is_a_judgement_not_a_failure():
    for reply in ('{"best": []}', '{"best": ["x"], "answerable": 0.9}'):
        result = await LlmRanker(Client(reply)).rank("q", [_ctx(1), _ctx(2)])
        assert result.order == [0, 1] and max(result.probabilities) == 0.001 and result.answerable <= 0.2


@pytest.mark.asyncio
async def test_scope_is_a_probability():
    assert await LlmRanker(Client('{"in_scope": 0.93}')).scope("Nogironlik pensiyasi?") == pytest.approx(0.93)
    assert await LlmRanker(Client('{"in_scope": 7}')).scope("q") == 1.0
    assert await LlmRanker(Client("???")).scope("q") is None


@pytest.mark.asyncio
async def test_jev_ranker_uses_the_fallback_only_when_enabled(monkeypatch):
    ctxs = [_ctx(i) for i in range(4)]
    client = Client('{"best": [2], "answerable": 0.8, "in_scope": 0.9}')
    ranker = JevRanker(client)
    assert (await ranker.rank("q", ctxs)).order[0] == 1
    assert await ranker.scope("q") == pytest.approx(0.9)
    monkeypatch.setattr(settings, "LLM_RANK_FALLBACK", False)
    assert await ranker.rank("q", ctxs) is None and await ranker.scope("q") is None


@pytest.mark.asyncio
async def test_with_jev_switched_off_openrouter_is_not_asked_at_all(monkeypatch):
    monkeypatch.setattr(settings, "JEV_ENABLED", False)

    class NoJev(Client):
        async def decide(self, *a, **k):
            raise AssertionError("Jev must not be called")

    client = NoJev('{"best": [1], "answerable": 0.7, "in_scope": 0.8}')
    assert (await JevRanker(client).rank("q", [_ctx(1), _ctx(2)])).order[0] == 0
    assert await JevRanker(client).scope("q") == pytest.approx(0.8)
