"""
The answer is written in the language of the question (Uzbek in Latin or Cyrillic, Russian, English). The units and
every vector are Uzbek, so a Russian or English question is searched through an Uzbek translation, but the reader gets
the answer, the disclaimer, the refusal and the source heading in their own language.
"""
import json
import re

import httpx
import pytest

from src.api.app import app
from src.api.routes.query import QueryRequest
from src.generation.prompts import DISCLAIMERS, REFUSAL_MESSAGES

RUSSIAN = "Какой размер пособия по инвалидности и кто его получает?"
ENGLISH = "What is the amount of the disability pension and who receives it?"
UZBEK_LATIN = "Nogironligi bo'lgan shaxslarga pensiya qancha to'lanadi?"
UZBEK_CYRILLIC = "Ногирони бўлган шахсларга пенсия қанча тўланади?"


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def _ask(question, **extra):
    async with _client() as c:
        res = await c.post("/api/v1/query", json={"question": question, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def _in_language(answer: str, language: str) -> bool:
    """The answer carries the texts the system adds in that language (a refusal or a disclaimer)."""
    texts = [DISCLAIMERS[language].strip("\n-* "), REFUSAL_MESSAGES[language]]
    return any(t[:40] in answer for t in texts) or (language == "uz")


@pytest.mark.asyncio
async def test_a_russian_question_is_answered_in_russian():
    body = await _ask(RUSSIAN)
    assert body["detected_language"] == "ru" and not body["answer"].startswith("Kechirasiz")
    assert re.search(r"[а-яё]{4,}", body["answer"]) and _in_language(body["answer"], "ru")
    assert "Eslatma" not in body["answer"]


@pytest.mark.asyncio
async def test_an_english_question_is_answered_in_english():
    body = await _ask(ENGLISH)
    assert body["detected_language"] == "en"
    assert not re.search(r"[а-яё]", body["answer"]) and _in_language(body["answer"], "en")
    assert "Eslatma" not in body["answer"]


@pytest.mark.asyncio
async def test_an_uzbek_question_is_answered_in_uzbek_in_the_script_of_the_question():
    latin = await _ask(UZBEK_LATIN)
    cyrillic = await _ask(UZBEK_CYRILLIC)
    assert latin["detected_language"] == cyrillic["detected_language"] == "uz"
    assert "Eslatma" in latin["answer"] or "Bu savolga" in latin["answer"]
    assert "Эслатма" in cyrillic["answer"] or "Бу саволга" in cyrillic["answer"]


@pytest.mark.asyncio
async def test_a_streamed_russian_question_ends_in_russian_too():
    async with _client() as c:
        res = await c.post("/api/v1/query?stream=true", json={"question": RUSSIAN})
    events = [json.loads(chunk[6:]) for chunk in res.text.split("\n\n") if chunk.startswith("data: ")]
    done = [e for e in events if e["type"] == "done"][0]
    assert done["language"] == "ru" and "Eslatma" not in json.dumps(done, ensure_ascii=False)


@pytest.mark.parametrize("language", ["auto", "uz", "ru", "en"])
def test_the_api_accepts_uzbek_russian_and_english(language):
    assert QueryRequest(question="Savol?", language=language).language == language
