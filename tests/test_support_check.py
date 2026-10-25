"""support_check.py uchun oflayn testlar: soxta client, tarmoq yo'q, data/store ga tegilmaydi."""
import re
from types import SimpleNamespace

import pytest

from src.config import settings
from src.generation import support_check
from src.generation.support_check import (
    Verdict,
    apply_verdicts,
    run_support_check,
    split_claims,
)

A15 = "orq641_art_15"
A16 = "orq641_art_16"
A17 = "orq641_art_17"
A20 = "orq641_art_20"

BULLET_OK = f"- Nogironligi bo'lgan shaxslarga imtiyoz beriladi [{A15}]."


def _verdicts(*pairs):
    return [Verdict(index=i, verdict=v, reason="test") for i, v in pairs]


class FakeArticle:
    def __init__(self, cid, text="Qonun bandi matni."):
        self.canonical_id = cid
        self._text = text
        self.metadata = None

    def get_text(self, language="uz"):
        return self._text


def _ctx(cid):
    return SimpleNamespace(article=FakeArticle(cid))


class FakeClient:
    """Navbatdagi javob/xatoni qaytaradigan soxta client; barcha chaqiruvlarni yozadi."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    async def chat_completion(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# --- split_claims ---

def test_split_claims_bullet():
    claims = split_claims(BULLET_OK)
    assert len(claims) == 1
    assert claims[0].kind == "bullet"
    assert claims[0].cited_ids == [A15]


def test_split_claims_numbered_steps():
    raw = f"1. Arizani topshiring [{A16}].\n2. Javobni kuting."
    claims = split_claims(raw)
    assert len(claims) == 1
    assert claims[0].kind == "step"
    assert claims[0].cited_ids == [A16]


def test_split_claims_lead_is_first_substantive_line():
    raw = f"Siz imtiyozga egasiz [{A15}].\n{BULLET_OK}"
    claims = split_claims(raw)
    assert [c.kind for c in claims] == ["lead", "bullet"]


def test_split_claims_sentence_with_two_citations_is_one_claim():
    raw = f"Kirish [{A15}].\nBu huquq [{A16}] va [{A17}] bilan tasdiqlanadi."
    claims = split_claims(raw)
    sent = [c for c in claims if c.kind == "sentence"]
    assert len(sent) == 1
    assert sent[0].cited_ids == [A16, A17]


def test_split_claims_ignores_lines_without_citations():
    raw = BULLET_OK + "\nBu shunchaki izoh.\nNima qilish kerak:"
    claims = split_claims(raw)
    assert len(claims) == 1
    assert claims[0].kind == "bullet"


def test_split_claims_uncited_lead_is_checked_against_every_cited_unit():
    # the direct answer is the sentence a reader trusts most: it must not escape the check for lack of a marker
    raw = f"Bu shunchaki kirish.\nNima qilish kerak:\n{BULLET_OK}\n- Boshqa band [{A16}]."
    claims = split_claims(raw)
    assert [c.kind for c in claims] == ["lead", "bullet", "bullet"]
    assert claims[0].text == "Bu shunchaki kirish."
    assert claims[0].cited_ids == [A15, A16]


def test_split_claims_bold_sentence_lead_is_not_taken_for_a_heading():
    lead = "**Ha, siz yordamchingiz bilan bepul foydalanish huquqiga egasiz, lekin bu huquq cheklangan.**"
    claims = split_claims(f"{lead}\n\n**Nima qilish kerak:**\n{BULLET_OK}")
    assert [c.kind for c in claims] == ["lead", "bullet"]
    assert claims[0].text == lead


def test_split_claims_answer_without_any_citation_has_no_claims():
    assert split_claims("**Ha, siz huquqqa egasiz, bu savolga aniq javob beriladi.**\nIzoh.") == []


# --- apply_verdicts ---

def test_apply_verdicts_drops_unsupported_bullet():
    raw = f"- Yolg'on imtiyoz [{A15}].\n- To'g'ri imtiyoz [{A16}]."
    claims = split_claims(raw)
    text, dropped = apply_verdicts(raw, claims, _verdicts((0, "unsupported"), (1, "supported")))
    assert dropped == 1
    assert A15 not in text
    assert "To'g'ri imtiyoz" in text


def test_apply_verdicts_renumbers_remaining_steps():
    raw = f"1. Birinchi [{A15}].\n2. Ikkinchi [{A16}].\n3. Uchinchi [{A17}]."
    claims = split_claims(raw)
    text, dropped = apply_verdicts(
        raw, claims, _verdicts((0, "supported"), (1, "unsupported"), (2, "supported")))
    assert dropped == 1
    assert re.findall(r"(?m)^\d+\.", text) == ["1.", "2."]
    assert "Uchinchi" in text


def test_apply_verdicts_drops_header_when_all_steps_gone():
    raw = f"Nima qilish kerak:\n1. Birinchi [{A15}].\n2. Ikkinchi [{A16}]."
    claims = split_claims(raw)
    assert len(claims) == 2
    text, dropped = apply_verdicts(raw, claims, _verdicts((0, "unsupported"), (1, "unsupported")))
    assert dropped == 2
    assert "Nima qilish kerak" not in text
    assert "Birinchi" not in text


def test_apply_verdicts_sentence_removes_only_bad_marker():
    raw = f"Kirish ma'lumot.\nSizga to'lov beriladi [{A15}]."
    claims = split_claims(raw)
    assert claims[-1].kind == "sentence"
    text, dropped = apply_verdicts(raw, claims, _verdicts((claims[-1].index, "unsupported"),))
    assert dropped == 0   # a sentence stays; only its citation mark is removed
    assert f"[{A15}]" not in text
    assert "Sizga to'lov beriladi" in text


def test_apply_verdicts_partial_and_supported_untouched():
    raw = BULLET_OK
    claims = split_claims(raw)
    text, dropped = apply_verdicts(raw, claims, _verdicts((0, "partial"),))
    assert (text, dropped) == (raw, 0)


# --- run_support_check ---

def _enable(monkeypatch):
    monkeypatch.setattr(settings, "SUPPORT_CHECK_ENABLED", True)


async def test_run_support_check_bad_json_keeps_answer(monkeypatch):
    _enable(monkeypatch)
    client = FakeClient(["salom, bu JSON emas"])
    raw = BULLET_OK
    out, warnings = await run_support_check(raw, "savol", [_ctx(A15)], client)
    assert out == raw
    assert warnings == ["support_check_skipped"]


async def test_run_support_check_exception_keeps_answer(monkeypatch):
    _enable(monkeypatch)
    client = FakeClient([RuntimeError("tarmoq uzildi")])
    out, warnings = await run_support_check(BULLET_OK, "savol", [_ctx(A15)], client)
    assert out == BULLET_OK
    assert warnings == ["support_check_skipped"]


async def test_run_support_check_disabled_never_calls_client(monkeypatch):
    monkeypatch.setattr(settings, "SUPPORT_CHECK_ENABLED", False)
    client = FakeClient(['[{"i": 0, "verdict": "unsupported", "reason": "x"}]'])
    out, warnings = await run_support_check(BULLET_OK, "savol", [_ctx(A15)], client)
    assert client.calls == []
    assert (out, warnings) == (BULLET_OK, [])


async def test_run_support_check_lead_regenerates_once_without_loop(monkeypatch):
    _enable(monkeypatch)
    raw = f"Sizga yordam beriladi [{A15}].\n\n- Qo'shimcha imtiyoz [{A20}]."
    regen = (f"Yangilangan javob matni shu yerda keltirilgan [{A20}] "
             f"qo'shimcha tushuntirish bilan yana davom etadi.")
    assert len(regen) >= 50
    client = FakeClient([
        json_verdicts([(0, "unsupported"), (1, "supported")]),
        regen,
        json_verdicts([(0, "supported")]),
    ])
    out, warnings = await run_support_check(
        raw, "savol", [_ctx(A15), _ctx(A20)], client,
        original_messages=[{"role": "user", "content": "savol"}],
    )
    assert len(client.calls) == 3  # check, regen, qayta check; ikkinchi sikl yo'q
    assert any("regenerated" in w for w in warnings)
    assert A20 in out


async def test_run_support_check_refusal_never_calls_client(monkeypatch):
    _enable(monkeypatch)
    client = FakeClient(['[{"i": 0, "verdict": "unsupported", "reason": "x"}]'])
    raw = "So'rovingiz bo'yicha aniq norma yoki qoida topilmadi."
    out, warnings = await run_support_check(raw, "savol", [], client)
    assert client.calls == []
    assert (out, warnings) == (raw, [])


def json_verdicts(pairs):
    import json as _json
    return _json.dumps([{"i": i, "verdict": v, "reason": "test"} for i, v in pairs])


def test_split_claims_empty():
    assert split_claims("") == []
    assert split_claims("   \n  ") == []


def test_apply_verdicts_no_claims_returns_input():
    assert apply_verdicts(BULLET_OK, [], []) == (BULLET_OK, 0)


@pytest.mark.parametrize("flag", [True, False])
def test_support_check_module_flag_respected(flag, monkeypatch):
    monkeypatch.setattr(settings, "SUPPORT_CHECK_ENABLED", flag)
    assert support_check.settings.SUPPORT_CHECK_ENABLED is flag
