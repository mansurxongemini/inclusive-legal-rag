import pytest
from src.generation.prompts import build_system_prompt, ResponseMode


def test_system_prompt_practical_guidance_mandate():
    prompt = build_system_prompt(language="uz", mode="plain")
    assert "AMALIY YO'NALTIRISH" in prompt
    assert "Nima va Nega" in prompt
    assert "Kim vakolatdor va Qayerga borish kerak" in prompt
    assert "Qanday qilaman" in prompt
    assert "Muddatlar va talablar" in prompt


def test_system_prompt_subsumption_mode():
    prompt = build_system_prompt(language="uz", mode="subsumption")
    assert "CHUQUR HUQUQIY TAHLIL VA SUBSUMSIYA REJIMI" in prompt
    assert "HUQUQIY ASOS" in prompt
    assert "QO'LLANILISH SHARTLARI" in prompt
    assert "AMALIY XULOSA" in prompt
