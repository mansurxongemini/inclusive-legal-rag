"""
Answer guards, sources-only mode and the verified stream: the finished answer is checked for script, wording and
numbers, repaired once, and the `done` event carries the verified text.
"""
import json
from types import SimpleNamespace

import pytest

from src.config import settings
from src.gateway.service import cache_keys
from src.generation import guards
from src.generation.answer_checks import uncited_ratio
from src.generation.degraded import sources_only_text
from src.generation.generator import AnswerGenerator
from src.generation.prompts import disclaimer_for, disclaimer_text, refusal_for
from src.generation.validator import CitationValidator
from src.retrieval.reranker import RetrievedArticleContext
from src.schema.canonical import CanonicalArticle

TEXT_UZ = ("1. Nogironligi bo'lgan shaxsga 1 500 000 so'm miqdorida bir martalik yordam beriladi.\n"
           "2. Ariza 30 kun ichida ko'rib chiqiladi.")


def _ctx(cid="vmq_10_2024_p_5"):
    art = CanonicalArticle(
        canonical_id=cid,
        metadata={
            "law_id": "vmq_10_2024", "law_title": {"uz": "Yordam tartibi", "ru": "Порядок помощи"},
            "law_number": "VMQ-10", "article_number": "5-band", "article_title": {"uz": "Bir martalik yordam"},
            "source_url": "https://lex.uz/docs/1", "effective_date": "2024-01-01", "promulgation_date": "2024-02-15",
            "last_verified_date": "2026-10-01", "source_hash": "sha256:x", "category": "social_protection",
        },
        translations={"uz": TEXT_UZ},
    )
    return RetrievedArticleContext(article=art, final_score=1.0, source_tag="primary")


class Client:
    """LLM stub: answers come from `replies` in order; the stream yields `stream_text` in two parts."""

    is_mock = False
    primary_model = "test/model"

    def __init__(self, replies=(), stream_text=""):
        self.replies, self.calls, self.stream_text = list(replies), [], stream_text

    async def chat_completion(self, messages, **kwargs):
        self.calls.append(messages)
        return self.replies.pop(0)

    async def chat_completion_stream(self, messages, **kwargs):
        half = len(self.stream_text) // 2
        yield self.stream_text[:half]
        yield self.stream_text[half:]


GOOD = "**Yordam 1 500 000 so'm.** [vmq_10_2024_p_5]\n\n- Ariza 30 kun ichida ko'riladi. [vmq_10_2024_p_5]"
BAD_NUMBER = "**Yordam 2 000 000 so'm.** [vmq_10_2024_p_5]\n\n- Ariza 60 kun ichida ko'riladi. [vmq_10_2024_p_5]"


# --- guards --------------------------------------------------------------------------------------------------------

def test_numbers_of_the_act_label_are_allowed_but_invented_ones_are_not():
    ctxs = [_ctx()]
    ok = "Bu VMQ-10 qarorining 5-bandi, 2024-yil 15-fevraldagi qaror bo'yicha 1 500 000 so'm [vmq_10_2024_p_5]."
    assert guards.find_issues("savol", ok, ctxs, "uz")["numbers"] == []
    assert guards.find_issues("savol", BAD_NUMBER, ctxs, "uz")["numbers"] == ["2000000", "60"]


def test_a_cyrillic_question_needs_a_cyrillic_answer_but_the_disclaimer_does_not_count():
    ctxs = [_ctx()]
    lat = "**Yordam beriladi.** [vmq_10_2024_p_5]"
    assert guards.find_issues("Ёрдам берилами?", lat, ctxs, "uz")["script"] is True
    cyr = "**Ёрдам берилади.** [vmq_10_2024_p_5]" + disclaimer_for("uz", "Ёрдам берилами?")
    assert guards.find_issues("Ёрдам берилами?", cyr, ctxs, "uz")["script"] is False
    lat_with_latin_disclaimer = "**Ёрдам берилади.** [vmq_10_2024_p_5]" + disclaimer_for("uz", "Yordam beriladimi?")
    assert guards.find_issues("Ёрдам берилами?", lat_with_latin_disclaimer, ctxs, "uz")["script"] is False


@pytest.mark.asyncio
async def test_a_failing_answer_is_regenerated_once_with_the_problems_named():
    client = Client(replies=[GOOD])
    text, warnings = await guards.guard_answer(client, [{"role": "user", "content": "q"}], BAD_NUMBER, "Yordam qancha?", [_ctx()], "uz")
    assert text == GOOD and warnings == ["answer_repaired"]
    instruction = client.calls[0][-1]["content"]
    assert "2000000" in instruction and "60" in instruction and client.calls[0][-2]["role"] == "assistant"


@pytest.mark.asyncio
async def test_a_repair_that_is_not_better_keeps_the_original_and_reports_the_problems():
    client = Client(replies=[BAD_NUMBER])
    text, warnings = await guards.guard_answer(client, [], BAD_NUMBER, "Yordam qancha?", [_ctx()], "uz")
    assert text == BAD_NUMBER and warnings == ["ungrounded_numbers: 2000000, 60"]
    assert len(client.calls) == 1                                    # one repair round, never a loop


NEIGHBOUR_ID = GOOD + "\n- Ariza elektron beriladi. [vmq_10_2024_p_6]"


def test_a_citation_of_a_unit_the_model_was_not_given_is_an_issue():
    # seen live: shown point 44 of a regulation (whose text also carries points 46-48), the model cited [..._p_46]
    issues = guards.find_issues("Yordam qancha?", NEIGHBOUR_ID, [_ctx()], "uz")
    assert issues["unknown_ids"] == ["vmq_10_2024_p_6"] and guards.issue_count(issues) == 1
    assert guards.find_issues("Yordam qancha?", GOOD, [_ctx()], "uz")["unknown_ids"] == []


@pytest.mark.asyncio
async def test_an_unknown_citation_is_repaired_by_naming_it():
    client = Client(replies=[GOOD])
    text, warnings = await guards.guard_answer(client, [], NEIGHBOUR_ID, "Yordam qancha?", [_ctx()], "uz")
    assert text == GOOD and warnings == ["answer_repaired"]
    assert "[vmq_10_2024_p_6]" in client.calls[0][-1]["content"]


def test_validator_reports_the_citations_it_had_to_remove():
    result = CitationValidator.validate_and_sanitize(NEIGHBOUR_ID, [_ctx()], "uz")
    assert result.is_valid is False and "vmq_10_2024_p_6" not in result.clean_answer
    assert any(w.startswith("unresolved_citations: vmq_10_2024_p_6") for w in result.warnings)


@pytest.mark.asyncio
async def test_clean_answers_cost_no_extra_call_and_guards_can_be_switched_off(monkeypatch):
    client = Client(replies=[GOOD])
    assert await guards.guard_answer(client, [], GOOD, "Yordam qancha?", [_ctx()], "uz") == (GOOD, [])
    assert client.calls == []
    monkeypatch.setattr(settings, "ANSWER_GUARDS_ENABLED", False)
    assert await guards.guard_answer(client, [], BAD_NUMBER, "Yordam qancha?", [_ctx()], "uz") == (BAD_NUMBER, [])


# --- localized texts -----------------------------------------------------------------------------------------------

def test_disclaimer_and_refusal_follow_the_script_of_the_question():
    assert "Эслатма" in disclaimer_for("uz", "Ёрдам берилами?") and "Eslatma" in disclaimer_for("uz", "Yordam beriladimi?")
    assert "Примечание" in disclaimer_for("ru", "Положено ли?") and "Disclaimer" in disclaimer_for("en", "Is it?")
    assert refusal_for("uz", "Ёрдам берилами?").startswith("Бу саволга")
    assert refusal_for("uz", "Yordam beriladimi?").startswith("Bu savolga")
    assert disclaimer_text("uz", "cyrillic").startswith("Ушбу") and disclaimer_text("uz").startswith("Ushbu")


# --- sources-only mode ---------------------------------------------------------------------------------------------

def test_sources_only_text_quotes_the_norms_with_their_ids():
    text = sources_only_text([_ctx()], "uz", query="Yordam qancha?")
    assert "ishlamayapti" in text and "Yordam tartibi (VMQ-10), 5-band" in text and "[vmq_10_2024_p_5]" in text
    assert "1 500 000" in text
    assert "ишламаяпти" in sources_only_text([_ctx()], "uz", query="Ёрдам қанча?")


@pytest.mark.asyncio
async def test_generator_serves_the_matching_norms_when_every_model_fails():
    class Down(Client):
        async def chat_completion(self, messages, **kwargs):
            raise RuntimeError("All configured LLM models failed")

    result = await AnswerGenerator(client=Down()).generate_answer("Yordam qancha?", [_ctx()], "uz")
    assert result.degraded and result.citations and result.validation_passed
    assert any(w.startswith("llm_unavailable") for w in result.warnings)
    assert "1 500 000" in result.clean_answer


# --- verified stream -----------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_done_event_carries_the_repaired_answer():
    client = Client(replies=[GOOD], stream_text=BAD_NUMBER)
    events = []
    async for sse in AnswerGenerator(client=client).generate_answer_stream("Yordam qancha?", [_ctx()], "uz"):
        events.append(json.loads(sse[6:]))
    kinds = [e["type"] for e in events]
    assert kinds[-1] == "done" and "status" in kinds
    done = events[-1]
    assert "1 500 000" in done["clean_answer"] and "2 000 000" not in done["clean_answer"]
    assert done["warnings"][0] == "answer_repaired" and done["citations"] and done["degraded"] is False


# --- smaller pieces ------------------------------------------------------------------------------------------------

def test_cache_key_separates_scripts_and_answer_versions(monkeypatch):
    latin = SimpleNamespace(detected_language="uz", detected_script="latin")
    cyrillic = SimpleNamespace(detected_language="uz", detected_script="cyrillic")
    assert cache_keys(latin, "plain") != cache_keys(cyrillic, "plain")
    before = cache_keys(latin, "plain")
    monkeypatch.setattr(settings, "GENERATION_MODEL_PRIMARY", "other-model")
    assert cache_keys(latin, "plain") != before
    # a data or pipeline fix bumps ANSWER_VERSION, so answers cached before it (e.g. quoting a shifted Russian text) expire
    import src.gateway.service as service
    current = cache_keys(latin, "plain")
    monkeypatch.setattr(service, "ANSWER_VERSION", "1999-01-01.1")
    assert cache_keys(latin, "plain") != current


def test_refusal_wording_the_prompt_prescribes_is_recognised_for_short_answers_only():
    short = "Bu savolga aniq javob bera olmayman. Vakolatli organga murojaat qiling."
    assert CitationValidator._detect_refusal(short, set())
    substantive = ("Nogironligi bo'lgan shaxsga bir martalik yordam beriladi [vmq_10_2024_p_5]. " * 8
                   + "Muddat bo'yicha aniq javob bera olmayman.")
    assert not CitationValidator._detect_refusal(substantive, {"vmq_10_2024_p_5"})


def test_markers_after_the_full_stop_belong_to_their_sentence():
    answer = ("Nogironligi bo'lgan shaxsga bir martalik yordam to'lanadi. [1]\n"
              "- Ariza o'ttiz kun ichida ko'rib chiqiladi va qaror chiqariladi. [2]\n"
              "- Uchinchi gap hech qanday manbaga tayanmaydi va shuning uchun belgisizdir.")
    assert uncited_ratio(answer) == pytest.approx(1 / 3, abs=0.01)


@pytest.mark.asyncio
async def test_a_hung_generation_is_cut_off_and_the_norms_are_shown(monkeypatch):
    import asyncio

    async def hang(self, *a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr(AnswerGenerator, "generate_answer", hang)
    monkeypatch.setattr(settings, "ANSWER_TIMEOUT_S", 0.2)
    from tests.test_security_and_regressions import local_client      # in-process app with the mock store
    async with local_client() as c:
        res = await c.post("/api/v1/query", json={"question": "Nogironlik guruhini qayta ko'rikdan o'tkazish tartibi qanday?", "language": "uz"})
    assert res.status_code == 200 and res.json()["degraded"] is True and res.json()["citations"]
