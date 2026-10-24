"""Long chat questions that tell a story are also searched through short legal sub-questions written by the LLM."""
import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import settings
from src.nlp.query_analyzer import QueryAnalyzer
from src.nlp.query_translator import MAX_SUBQUESTIONS, QueryTranslator, _parse_subquestions
from src.retrieval.hybrid_retriever import HybridRetriever, ScoredArticle
from src.retrieval.pipeline import fuse_aspect_candidates, retrieve_contexts
from src.schema.canonical import ArticleMetadata, ArticleStatus, CanonicalArticle

# A real chat question (Cyrillic, Karakalpak words, typos): the social-registry application was refused by SMS and
# the "Inson" centre gave no answer. Its own words find only the SMS rule; the answer is in VMQ-35 (2026).
REFUSED_REGISTRY_STORY = (
    "Ассалаумаликум мен 1 гурух ногироныман хозирда ижарада турипман умрлик юоддашим ишсиз ичтимойи рестрга утмакши "
    "булип ариза ташладим лекин жавоп келмади .Кейнг узлари меники шакирип ташакурнама йоздирип рестрга утасиз деп "
    "ариза калдирдим Лекин еки кунан сунг телефонимга аризан рад этилди деп смс келдим Инсан социал орайига "
    "барганимда улардан мазмунли жавоп алмадим нимага маслахат бера оласиз олдинан рахмат"
)
# The live retrieval check of this story (VMQ-35 annex 4 appeal units, annex 1 refusal units) is gold-set item uz26,
# run on the real corpus by eval/run_eval.py.


def _scored(cid: str, rrf: float, bm25_rank=None, vector_rank=None) -> ScoredArticle:
    return ScoredArticle(canonical_id=cid, rrf_score=rrf, bm25_rank=bm25_rank, vector_rank=vector_rank)


def test_parse_subquestions_keeps_short_latin_questions_only():
    raw = (
        'Mana savollar:\n["Ijtimoiy reyestrga kiritish qanday asoslarda rad etiladi?", '
        '"Ижтимоий реестрга киритиш рад этилса нима қилиш керак?", "Qisqa", '
        '"ijtimoiy reyestrga kiritish qanday asoslarda rad etiladi?", '
        '"Ijtimoiy reyestrga kiritishni rad etish ustidan qayerga shikoyat qilinadi?", '
        '"Shikoyat qancha muddatda ko\'rib chiqiladi?", "Shikoyat uchun to\'lov olinadimi?", '
        '"Sudga murojaat qilish mumkinmi?"]'
    )
    assert _parse_subquestions(raw) == [
        "Ijtimoiy reyestrga kiritish qanday asoslarda rad etiladi?",
        "Ijtimoiy reyestrga kiritishni rad etish ustidan qayerga shikoyat qilinadi?",
        "Shikoyat qancha muddatda ko'rib chiqiladi?",
        "Shikoyat uchun to'lov olinadimi?",
    ]
    assert len(_parse_subquestions(raw)) == MAX_SUBQUESTIONS
    assert _parse_subquestions("Kechirasiz, savolni tushunmadim.") == []
    assert _parse_subquestions('["buzilgan json",') == []
    assert _parse_subquestions('{"q": "Ijtimoiy reyestr nima?"}') == []


def test_legal_subquestions_calls_the_llm_once_per_question():
    QueryTranslator._cache.clear()
    client = MagicMock(is_mock=False)
    client.chat_completion = AsyncMock(return_value='["Ijtimoiy reyestrga kiritish qanday asoslarda rad etiladi?"]')
    first = asyncio.run(QueryTranslator.legal_subquestions(REFUSED_REGISTRY_STORY, client))
    first.append("caller's own change")
    again = asyncio.run(QueryTranslator.legal_subquestions(REFUSED_REGISTRY_STORY, client))
    assert again == ["Ijtimoiy reyestrga kiritish qanday asoslarda rad etiladi?"]
    assert client.chat_completion.await_count == 1
    kwargs = client.chat_completion.await_args.kwargs
    assert kwargs["reasoning"] == {"enabled": False} and kwargs["temperature"] == 0.0

    QueryTranslator._cache.clear()
    client.chat_completion = AsyncMock(return_value="Bu savol emas")
    assert asyncio.run(QueryTranslator.legal_subquestions(REFUSED_REGISTRY_STORY, client)) is None
    client.chat_completion = AsyncMock(side_effect=RuntimeError("provider down"))
    assert asyncio.run(QueryTranslator.legal_subquestions(REFUSED_REGISTRY_STORY, client)) is None
    assert asyncio.run(QueryTranslator.legal_subquestions("savol", MagicMock(is_mock=True))) is None


def test_fusion_gives_each_sub_question_its_first_hits():
    # the story's own hits carry large raw scores (summed over the original and the rewrite)
    base = [_scored(f"story_{i}", 0.30 - i * 0.01) for i in range(25)]
    appeal = [_scored("appeal_council", 0.02), _scored("story_3", 0.02)] + [_scored(f"code_{i}", 0.02) for i in range(12)]
    # a unit the dense search ranks first sits low in its sub-question's list: lexical hits of generic laws lead it
    grounds = [_scored(f"law_{i}", 0.05, bm25_rank=i + 1) for i in range(15)] + [_scored("refusal_grounds", 0.02, vector_rank=1)]

    fused = fuse_aspect_candidates(base, [appeal, grounds], limit=12)
    ids = [c.canonical_id for c in fused]
    assert len(ids) == 12 and len(set(ids)) == 12
    # a sub-question's first hit beats the story's second hit, whatever the raw scores
    assert ids.index("appeal_council") < ids.index("story_1")
    assert ids.index("refusal_grounds") < ids.index("story_1")
    assert ids.index("refusal_grounds") < ids.index("law_1")
    assert ids[0] == "story_3"                                     # found by the story and by a sub-question
    assert [c.rrf_score for c in fused] == sorted((c.rrf_score for c in fused), reverse=True)
    # the inputs are left as they were
    assert base[0].rrf_score == pytest.approx(0.30) and appeal[0].rrf_score == 0.02


def _make_ctx(i: int):
    from src.retrieval.reranker import RetrievedArticleContext
    meta = ArticleMetadata(
        law_id="test_law", law_title={"uz": "Qaror"}, law_number="VMQ-35", article_number=f"{i}-band",
        article_title={"uz": f"Band {i}"}, source_url="https://lex.uz", effective_date="2026-01-01",
        last_verified_date="2026-01-01", source_hash=f"sha256:h_{i}", status=ArticleStatus.ACTIVE,
        category="disability_rights",
    )
    art = CanonicalArticle(canonical_id=f"unit_{i}", metadata=meta, translations={"uz": f"Matn {i}"})
    return RetrievedArticleContext(article=art, final_score=1.0, source_tag="primary")


async def test_jev_scores_a_passage_by_its_best_choice_over_the_sub_questions():
    from src.retrieval.jev_ranker import JevRanker

    seen = {}

    class StubClient:
        async def decide(self, state, questions, model=None, timeout=None):
            seen["questions"] = questions
            return {"answers": {
                "best": {"probabilities": {"p1": 0.9, "p2": 0.05, "p3": 0.05}},
                "answerable": {"noul": 0.8},
                "sub1": {"probabilities": {"p1": 0.1, "p2": 0.1, "p3": 0.8}},
                "sub2": {"probabilities": {"p1": 0.2, "p2": 0.3, "p3": 0.5}},
            }}

    subs = ["Ijtimoiy reyestrga kiritish qanday asoslarda rad etiladi?",
            "Ijtimoiy reyestrga kiritishni rad etish ustidan qayerga shikoyat qilinadi?"]
    result = await JevRanker(client=StubClient()).rank("savol", [_make_ctx(1), _make_ctx(2), _make_ctx(3)], subquestions=subs)
    assert set(seen["questions"]) == {"best", "answerable", "sub1", "sub2"}
    assert subs[1] in seen["questions"]["sub2"]["instructions"]
    assert seen["questions"]["sub1"]["criteria"] == seen["questions"]["best"]["criteria"]
    assert result.probabilities == [0.9, 0.3, 0.8]
    assert result.order == [0, 2, 1]
    assert result.answerable == 0.8


async def test_jev_sees_more_units_for_each_sub_question(monkeypatch):
    from src.retrieval.reranker import Reranker

    monkeypatch.setattr(settings, "RERANK_PROVIDER", "jev")
    monkeypatch.setattr(settings, "JEV_RERANK_UNITS", 3)
    monkeypatch.setattr(settings, "JEV_RERANK_UNITS_PER_SUBQUESTION", 2)
    contexts = {f"unit_{i}": _make_ctx(i).article for i in range(10)}

    class FakeStore:
        def get_articles_batch(self, cids):
            return {c: contexts[c] for c in cids if c in contexts}

    sent = {}

    class StubClient:
        is_mock = False

        async def decide(self, state, questions, model=None, timeout=None):
            sent["n"] = len(questions["best"]["criteria"])
            sent["subs"] = sorted(k for k in questions if k.startswith("sub"))
            return {"answers": {"best": {"probabilities": {"p1": 1.0}}, "answerable": {"noul": 0.9}}}

    candidates = [_scored(f"unit_{i}", 1.0 - i / 10) for i in range(10)]
    reranker = Reranker(client=StubClient())
    await reranker.rerank("savol", "uz", candidates, FakeStore(), top_n=2, subquestions=["Birinchi savol?", "Ikkinchi savol?"])
    assert sent == {"n": 7, "subs": ["sub1", "sub2"]}
    await reranker.rerank("savol", "uz", candidates, FakeStore(), top_n=2)
    assert sent == {"n": 3, "subs": []}


async def test_long_question_is_searched_through_its_sub_questions(monkeypatch, tmp_path):
    from src.clients.openrouter import OpenRouterClient
    from src.storage.hybrid_store import HybridStore

    store = HybridStore(str(tmp_path / "store"))
    client = OpenRouterClient()
    await store.seed_from_file("tests/fixtures/synthetic_pilot.json", client=client)

    subs = ["Nogironligi bo'lgan shaxslarga protez-ortopediya buyumlari qanday beriladi?",
            "Nogironligi bo'lgan xodimning ish vaqti qancha?"]
    asked: List[str] = []

    async def fake_subquestions(query, client):
        asked.append(query)
        return list(subs)

    searched: List[str] = []
    real_retrieve = HybridRetriever.retrieve

    async def spy_retrieve(self, analysis, *args, **kwargs):
        searched.append(analysis.normalized_query)
        return await real_retrieve(self, analysis, *args, **kwargs)

    monkeypatch.setattr(QueryTranslator, "legal_subquestions", fake_subquestions)
    monkeypatch.setattr(HybridRetriever, "retrieve", spy_retrieve)
    monkeypatch.setattr(settings, "QUERY_SUBQUESTIONS_MIN_WORDS", 25)

    story = ("Assalomu alaykum men ikkinchi guruh nogironiman zavodda ishlayman oyog'imni yo'qotganman protez kerak "
             "edi poliklinikaga bordim navbat ko'p dedi rahbarim esa har kuni kechgacha ishlatadi qo'shimcha haq ham "
             "bermaydi nima qilsam bo'ladi maslahat bering rahmat")
    analysis = QueryAnalyzer.analyze(story)
    assert len(analysis.normalized_query.split()) >= 25
    res = await retrieve_contexts(analysis=analysis, store=store, client=client, top_k=5, max_extra=0,
                                  rerank_top_n=3, apply_gate=False)
    assert asked == [story]
    assert res.signals["subquestions"] == subs
    assert searched[1:] == subs
    assert "synthetic_law_art_45" in [c.canonical_id for c in res.candidates]

    asked.clear()
    res = await retrieve_contexts(analysis=QueryAnalyzer.analyze("Protez qanday beriladi?"), store=store,
                                  client=client, top_k=5, max_extra=0, rerank_top_n=3, apply_gate=False)
    assert asked == [] and res.signals["subquestions"] == []
