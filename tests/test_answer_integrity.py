"""
Answer integrity: no citation is invented for the model, the disclaimer follows validation, the assistant API
reports validation_passed, importers store only languages that exist, and streamed answers are cached.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api.cache import QueryCache
from src.generation.generator import MAX_ANSWER_TOKENS, attach_disclaimer
from src.generation.prompts import DISCLAIMERS, build_system_prompt
from src.generation.validator import CitationValidator
from src.ingestion.localized import localized, provenance_for
from src.retrieval.reranker import RetrievedArticleContext
from src.schema.canonical import CanonicalArticle

PILOT = Path("data/pilot_laws/law_disability_2020.json")


def _ctx():
    with open(PILOT, "r", encoding="utf-8") as f:
        article = CanonicalArticle.model_validate(json.load(f)[0])
    return RetrievedArticleContext(article=article, final_score=1.0, source_tag="rrf")


# --- validator: no citation is attached on the model's behalf ---------------------------------------------------

def test_uncited_answer_gets_no_invented_citation():
    ctx = _ctx()
    res = CitationValidator.validate_and_sanitize(
        "Bu javob hech qanday normaga tayanmaydi va umumiy mulohazalardan iborat. " * 4, [ctx], "uz"
    )
    assert res.is_valid is False
    assert res.resolved_citations == []
    assert ctx.article.canonical_id not in res.sanitized_answer
    assert ctx.article.canonical_id not in res.clean_answer
    assert any("no_explicit_citation" in w for w in res.warnings)


def test_cited_answer_keeps_its_own_citation_only():
    ctx = _ctx()
    cid = ctx.article.canonical_id
    res = CitationValidator.validate_and_sanitize(f"Tibbiy yordam bepul ko'rsatiladi [{cid}]. " * 2, [ctx], "uz")
    assert res.is_valid and [c.canonical_id for c in res.resolved_citations] == [cid]


# --- disclaimer comes after the validated answer and before the sources footer ----------------------------------

def test_disclaimer_is_attached_after_validation_and_before_the_footer():
    ctx = _ctx()
    cid = ctx.article.canonical_id
    val = CitationValidator.validate_and_sanitize(f"Tibbiy yordam bepul ko'rsatiladi [{cid}]. " * 2, [ctx], "uz")
    disclaimer = DISCLAIMERS["uz"]
    assert "Eslatma" not in val.clean_answer

    answer, clean, telegram = attach_disclaimer(val, disclaimer, already_present=False)
    assert clean.endswith(disclaimer) and answer.endswith(disclaimer)
    assert telegram.index(disclaimer.strip()) < telegram.index("Asoslangan qonuniy manbalar")
    assert telegram.count("Eslatma") == 1

    # a disclaimer the model wrote itself is not repeated
    same = attach_disclaimer(val, disclaimer, already_present=True)
    assert same == (val.sanitized_answer, val.clean_answer, val.telegram_formatted)


# --- importers store only languages that exist ------------------------------------------------------------------

def test_uzbek_text_is_not_stored_as_russian_or_english():
    fields = localized("Nogironligi bo'lgan shaxslarga yordam beriladi.", "Nogironligi bo'lgan shaxslarga yordam beriladi.")
    assert fields == {"uz": "Nogironligi bo'lgan shaxslarga yordam beriladi."}
    assert set(provenance_for(fields)) == {"uz"}

    uz_cyrillic = "Ногиронлиги бўлган шахсларга ёрдам кўрсатилади"
    assert "ru" not in localized("Nogironligi bo'lgan shaxslarga yordam", uz_cyrillic)


def test_genuine_russian_is_kept_as_russian():
    russian = "В соответствии с настоящим законом лицам с инвалидностью предоставляется помощь."
    fields = localized("Ushbu qonunga muvofiq nogironligi bo'lgan shaxslarga yordam ko'rsatiladi.", russian)
    assert fields["ru"] == russian and set(provenance_for(fields)) == {"uz", "ru"}


def test_importers_do_not_copy_uzbek_text_into_ru_or_en():
    for name in ("url_importer", "document_inspector"):
        source = Path(f"src/ingestion/{name}.py").read_text(encoding="utf-8")
        assert not re.search(r'"uz":[^\n]*"ru":[^\n]*"en":', source), name


# --- generation limits and prompt ---------------------------------------------------------------------------------

def test_token_cap_and_no_invented_procedure_rule():
    assert MAX_ANSWER_TOKENS == 2048
    for mode in ("plain", "easy_read", "legal_text"):
        prompt = build_system_prompt(language="uz", mode=mode)
        assert "Never add a procedural step" in prompt
    assert "o'ylab topmang" in build_system_prompt(language="uz", mode="plain")


# --- streamed answers are cached -------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streamed_answer_is_cached_and_replayed(monkeypatch, tmp_path):
    from src.gateway import service

    cache = QueryCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("src.api.app.get_cache", lambda: cache)
    monkeypatch.setattr("src.api.app.get_store", lambda: None)
    monkeypatch.setattr("src.api.app.get_client", lambda: SimpleNamespace(is_mock=True))

    async def fake_retrieve(**kwargs):
        return SimpleNamespace(contexts=[object()], status_warnings=[], decision=None)

    calls = {"n": 0}
    text = "Nogironligi bo'lgan shaxslar uchun tibbiy yordam bepul ko'rsatiladi va davlat tomonidan kafolatlanadi [1]. " * 4

    class FakeGenerator:
        def __init__(self, client=None):
            pass

        async def generate_answer_stream(self, **kwargs):
            calls["n"] += 1
            yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"
            done = {"type": "done", "citations": [], "is_refusal": False, "validation_passed": True,
                    "clean_answer": text, "telegram_formatted": text, "warnings": [], "status_warnings": [],
                    "language": "uz", "mode": "plain"}
            yield f"data: {json.dumps(done)}\n\n"

    monkeypatch.setattr(service, "retrieve_contexts", fake_retrieve)
    monkeypatch.setattr(service, "AnswerGenerator", FakeGenerator)

    async def run():
        out = []
        async for chunk in service.answer_question_stream("Tibbiy yordam bepulmi?", language="uz"):
            out.append(json.loads(chunk.strip()[6:]))
        return out

    first = await run()
    second = await run()

    assert calls["n"] == 1, "the second request must be served from the cache"
    assert first[-1]["type"] == "done" and not first[-1].get("cached")
    assert second[0]["type"] == "token" and second[0]["text"] == text.strip()
    assert second[-1]["type"] == "done" and second[-1]["cached"] is True and second[-1]["validation_passed"] is True


# --- an exact cache hit of a streamed question costs no embedding ----------------------------------------------------

def _stream_fixture(monkeypatch, tmp_path):
    from src.gateway import service

    cache = QueryCache(str(tmp_path / "cache.db"))
    embeddings = []

    class FakeClient:
        is_mock = False

        async def get_embeddings(self, texts):
            embeddings.append(texts)
            return [[0.1] * 8]

    monkeypatch.setattr("src.api.app.get_cache", lambda: cache)
    monkeypatch.setattr("src.api.app.get_store", lambda: None)
    monkeypatch.setattr("src.api.app.get_client", lambda: FakeClient())

    async def events(question):
        return [json.loads(c.strip()[6:]) async for c in service.answer_question_stream(question, language="uz")]

    return service, cache, embeddings, events


@pytest.mark.asyncio
async def test_stream_exact_cache_hit_does_not_pay_for_an_embedding(monkeypatch, tmp_path):
    from src.nlp.query_analyzer import QueryAnalyzer

    service, cache, embeddings, events = _stream_fixture(monkeypatch, tmp_path)
    question = "Tibbiy yordam bepulmi?"
    text = "Nogironligi bo'lgan shaxslar uchun tibbiy yordam bepul ko'rsatiladi [1]. " * 6
    lang, mode = service.cache_keys(QueryAnalyzer.analyze(question, user_language="uz"), "plain")
    cache.set(question, lang, mode, {"answer": text, "clean_answer": text, "citations": [], "validation_passed": True})

    out = await events(question)

    assert embeddings == [], "the answer is already known: the embedding call is wasted money and latency"
    assert out[0]["type"] == "token" and out[0]["text"] == text
    assert out[-1]["cached"] is True and out[-1]["cache_type"].startswith("exact")


@pytest.mark.asyncio
async def test_stream_cache_miss_still_embeds_the_question_once(monkeypatch, tmp_path):
    service, cache, embeddings, events = _stream_fixture(monkeypatch, tmp_path)
    seen = {}

    async def fake_retrieve(**kwargs):
        seen["query_vector"] = kwargs["query_vector"]
        return SimpleNamespace(contexts=[], status_warnings=[], decision=None)

    class FakeGenerator:
        def __init__(self, client=None):
            pass

        async def generate_answer_stream(self, **kwargs):
            done = {"type": "done", "citations": [], "is_refusal": True, "validation_passed": False,
                    "clean_answer": "", "warnings": [], "status_warnings": []}
            yield f"data: {json.dumps(done)}\n\n"

    monkeypatch.setattr(service, "retrieve_contexts", fake_retrieve)
    monkeypatch.setattr(service, "AnswerGenerator", FakeGenerator)

    out = await events("Pensiya yoshi qanday belgilanadi?")

    assert len(embeddings) == 1 and seen["query_vector"] == [0.1] * 8      # the vector still reaches retrieval
    assert out[-1]["type"] == "done"
