import pytest
from pathlib import Path
from src.config import settings
from src.schema.canonical import CanonicalArticle
from src.retrieval.reranker import RetrievedArticleContext
from src.generation.prompts import build_system_prompt, format_context_for_llm, DISCLAIMERS
from src.generation.validator import CitationValidator
from src.generation.generator import AnswerGenerator
from src.clients.openrouter import OpenRouterClient


def create_sample_context():
    pilot_file = Path("tests/fixtures/synthetic_pilot.json")
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
    # grounding contract
    assert "ABSOLUTE RULES" in prompt_uz
    assert "SOURCES ONLY" in prompt_uz
    assert "NO INVENTION" in prompt_uz
    assert "CITE EVERY CLAIM" in prompt_uz
    assert "SAY WHAT IS MISSING" in prompt_uz
    assert "ODDIY TIL REJIMI" in prompt_uz

    prompt_legal = build_system_prompt("ru", "legal_text")
    assert "RASMIY MATN REJIMI" in prompt_legal
    assert "русском" in prompt_legal


def test_system_prompt_never_licenses_guessing():
    """The earlier prompt told the model to 'deduce' missing rules from general civil-law principles."""
    for mode in ("plain", "legal_text", "easy_read", "subsumption"):
        prompt = build_system_prompt("uz", mode).lower()
        assert "deduce" not in prompt
        assert "general principles" not in prompt
        assert "do not guess" in prompt


def test_citation_validator_valid():
    ctx = create_sample_context()
    raw_answer = (
        "Nogironligi bo'lgan shaxslar tibbiy ko'riklardan navbatsiz o'tish huquqiga ega [synthetic_law_art_15]. "
        "I va II guruh nogironlariga imtiyozli dori-darmonlar beriladi."
    )
    res = CitationValidator.validate_and_sanitize(raw_answer, [ctx], "uz")
    assert res.is_valid
    assert len(res.resolved_citations) >= 1
    assert res.resolved_citations[0].canonical_id == "synthetic_law_art_15"


def test_citation_validator_punctuation_spacing():
    ctx = create_sample_context()
    raw_answer = "Fuqarolar dori-darmon bilan ta'minlanadi [synthetic_law_art_15] ."
    res = CitationValidator.validate_and_sanitize(raw_answer, [ctx], "uz")
    assert res.is_valid
    # Must NOT have space before period: should be [1]. not [1] .
    assert "[1]." in res.clean_answer
    assert "[1] ." not in res.clean_answer


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


def test_build_system_prompt_plain_word_limit():
    plain_prompt = build_system_prompt(language="uz", mode="plain")
    assert "220 so'zdan oshmasin" in plain_prompt

    legal_prompt = build_system_prompt(language="uz", mode="legal_text")
    assert "220 so'zdan oshmasin" not in legal_prompt


def test_openrouter_provider_preferences(monkeypatch):
    client = OpenRouterClient()
    prefs = client.provider_preferences()
    assert prefs == {
        "order": ["deepinfra"],
        "allow_fallbacks": True,
        "quantizations": ["fp8", "fp16", "bf16", "fp32", "unknown"],
    }

    monkeypatch.setattr(settings, "LLM_PROVIDER_ORDER", "")
    monkeypatch.setattr(settings, "LLM_PROVIDER_QUANTIZATIONS", "")
    assert client.provider_preferences() is None


@pytest.mark.asyncio
async def test_chat_completion_sends_provider_and_reasoning():
    class StubHttpResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "x" * 40}}]}

    class StubHttpClient:
        is_closed = False

        def __init__(self):
            self.recorded_json = None

        async def post(self, url, json=None, **kwargs):
            self.recorded_json = json
            return StubHttpResponse()

    client = OpenRouterClient()
    client.is_mock = False
    stub_http = StubHttpClient()
    client._http_client = stub_http

    messages = [{"role": "user", "content": "Sinov savoli"}]
    reasoning_payload = {"effort": "low"}
    res = await client.chat_completion(
        messages=messages,
        reasoning=reasoning_payload,
    )
    assert res == "x" * 40
    assert stub_http.recorded_json is not None
    assert "provider" in stub_http.recorded_json
    assert stub_http.recorded_json["provider"] == {
        "order": ["deepinfra"],
        "allow_fallbacks": True,
        "quantizations": ["fp8", "fp16", "bf16", "fp32", "unknown"],
    }
    assert stub_http.recorded_json["reasoning"] == reasoning_payload



def test_reasoning_options_from_settings(monkeypatch):
    from src.generation.generator import _reasoning_options

    monkeypatch.setattr(settings, "GENERATION_REASONING_EFFORT", "")
    assert _reasoning_options() is None
    monkeypatch.setattr(settings, "GENERATION_REASONING_EFFORT", "none")
    assert _reasoning_options() == {"enabled": False}
    monkeypatch.setattr(settings, "GENERATION_REASONING_EFFORT", "low")
    assert _reasoning_options() == {"effort": "low"}
