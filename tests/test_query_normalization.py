"""Uzbek chat questions (Cyrillic, misspelled) are also searched through a standard-Latin rewrite."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.nlp.query_analyzer import QueryAnalyzer
from src.nlp.query_translator import QueryTranslator
from src.retrieval.pipeline import _use_uz_rewrite

NOISY = ("Давлат таминотидеги иштимоий рестирда тураман озик овкат ккийим кечак махсулотларини бир йилда нечи марта "
         "олсам булади вавчир еки картамга уткизса буладими?")
REWRITE = ("Davlat ta'minotidagi ijtimoiy reyestrda turaman. Oziq-ovqat, kiyim-kechak mahsulotlarini bir yilda necha "
           "marta olsam bo'ladi? Vaucher yoki bank plastik kartamga o'tkazsa bo'ladimi?")


def test_cyrillic_misspelled_question_uses_rewrite():
    assert _use_uz_rewrite(REWRITE, QueryAnalyzer.analyze(NOISY, user_language="uz"))


def test_clean_latin_question_skips_a_light_rewrite():
    q = "Nogironligi bo'lgan bolaga nafaqa qancha va qanday rasmiylashtiriladi?"
    rw = "Nogironligi bo'lgan bolaga nafaqa qancha va u qanday rasmiylashtiriladi?"
    assert not _use_uz_rewrite(rw, QueryAnalyzer.analyze(q, user_language="uz"))


def test_rewrite_in_cyrillic_or_runaway_is_rejected():
    QueryTranslator._cache.clear()
    client = MagicMock(is_mock=False)
    client.chat_completion = AsyncMock(return_value="Озиқ-овқат неча марта берилади?")
    assert asyncio.run(QueryTranslator.normalize_uzbek("ozik ovkat nechi marta", client)) is None
    client.chat_completion = AsyncMock(return_value="x " * 500)
    assert asyncio.run(QueryTranslator.normalize_uzbek("ozik ovkat nechi marta beriladi", client)) is None
    client.chat_completion = AsyncMock(return_value='"Oziq-ovqat necha marta beriladi?"')
    assert asyncio.run(QueryTranslator.normalize_uzbek("ozik ovkat nechi marta", client)) == "Oziq-ovqat necha marta beriladi?"


def test_mock_client_never_rewrites():
    assert asyncio.run(QueryTranslator.normalize_uzbek("savol", MagicMock(is_mock=True))) is None
