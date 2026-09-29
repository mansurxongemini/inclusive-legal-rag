import pytest
from pathlib import Path
from src.schema.canonical import CanonicalArticle
from src.retrieval.reranker import RetrievedArticleContext
from src.generation.prompts import build_system_prompt, format_context_for_llm, DISCLAIMERS
from src.generation.validator import CitationValidator
from src.generation.generator import AnswerGenerator
from src.clients.openrouter import OpenRouterClient


def create_sample_context():
    pilot_file = Path("data/pilot_laws/law_disability_2020.json")
    import json
    with open(pilot_file, "r") as f:
        data = json.load(f)
    art15 = CanonicalArticle.model_validate(data[2])  # art 15
    return RetrievedArticleContext(
        article=art15,
        final_score=0.95,
        source_tag="primary",
    )


def test_system_prompt_builder():
    prompt_uz = build_system_prompt("uz", "plain")
    assert "NON-NEGOTIABLE" in prompt_uz
    assert "SODDA VA TUSHUNARLI TIL REJIMI" in prompt_uz

    prompt_legal = build_system_prompt("ru", "legal_text")
    assert "YURIDIK RASMIY MATN REJIMI" in prompt_legal


def test_citation_validator_valid():
    ctx = create_sample_context()
    raw_answer = (
        "Nogironligi bo'lgan shaxslar tibbiy ko'riklardan navbatsiz o'tish huquqiga ega [law_disability_2020_art_15]. "
        "I va II guruh nogironlariga imtiyozli dori-darmonlar beriladi."
    )
    res = CitationValidator.validate_and_sanitize(raw_answer, [ctx], "uz")
    assert res.is_valid
    assert len(res.resolved_citations) >= 1
    assert res.resolved_citations[0].canonical_id == "law_disability_2020_art_15"


def test_citation_validator_refusal():
    raw_answer = "Qonunchilikda ushbu masala bo'yicha aniq norma yoki qoida topilmadi."
    res = CitationValidator.validate_and_sanitize(raw_answer, [], "uz")
    assert res.is_refusal
    assert res.is_valid


@pytest.mark.asyncio
async def test_answer_generator_end_to_end():
    ctx = create_sample_context()
    generator = AnswerGenerator()

    # Normal query
    answer_res = await generator.generate_answer(
        query="Nogironlar uchun tibbiy imtiyozlar bormi?",
        contexts=[ctx],
        language="uz",
        mode="plain",
    )

    assert answer_res.validation_passed
    assert len(answer_res.citations) >= 1
    assert "Eslatma" in answer_res.answer or "maslahat" in answer_res.answer

    # Empty context query (must refuse safely)
    refusal_res = await generator.generate_answer(
        query="Kosmik kemalarni soliqqa tortish tartibi",
        contexts=[],
        language="uz",
        mode="plain",
    )
    assert refusal_res.is_refusal
    assert refusal_res.validation_passed
