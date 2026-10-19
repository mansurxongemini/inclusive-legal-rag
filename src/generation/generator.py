import json
import logging
from typing import AsyncGenerator, Dict, List, Optional
from pydantic import BaseModel
from src.config import settings
from src.retrieval.reranker import RetrievedArticleContext
from src.clients.openrouter import OpenRouterClient
from src.generation.prompts import (
    build_system_prompt,
    format_context_for_llm,
    CURATED_INSTRUCTION,
    ANSWER_LANGUAGE_REMINDER,
    DISCLAIMERS,
    REFUSAL_MESSAGES,
    ResponseMode,
)


def _has_curated_context(contexts) -> bool:
    for ctx in contexts or []:
        art = getattr(ctx, "article", None)
        if art is None:
            continue
        if getattr(getattr(art, "metadata", None), "source_type", "lex") in ("curated", "huquqplus"):
            return True
        if (getattr(art, "canonical_id", "") or "").startswith(("qa_", "hp_")):
            return True
    return False
from src.generation.validator import CitationValidator, CitationItem, ValidationResult
from src.generation.support_check import run_support_check

logger = logging.getLogger(__name__)

STREAM_ERROR_MESSAGES = {
    "uz": "Javob yaratish xizmati vaqtincha mavjud emas. Iltimos, birozdan so'ng qayta urinib ko'ring.",
    "ru": "Сервис генерации ответов временно недоступен. Пожалуйста, повторите попытку позже.",
    "en": "The answer generation service is temporarily unavailable. Please try again shortly.",
}


def _reasoning_options() -> Optional[Dict]:
    """OpenRouter `reasoning` field from settings: "" = model default, "none" = off, otherwise an effort level."""
    effort = (settings.GENERATION_REASONING_EFFORT or "").strip().lower()
    if not effort:
        return None
    if effort == "none":
        return {"enabled": False}
    return {"effort": effort}


class GeneratedAnswer(BaseModel):
    answer: str
    clean_answer: str = ""
    telegram_formatted: str = ""
    citations: List[CitationItem]
    is_refusal: bool
    validation_passed: bool
    language: str
    mode: str
    warnings: List[str] = []


class AnswerGenerator:
    """
    Coordinates answer generation via OpenRouter with anti-hallucination guardrails and validation.
    """

    def __init__(self, client: Optional[OpenRouterClient] = None):
        self.client = client or OpenRouterClient()

    async def generate_answer(
        self,
        query: str,
        contexts: List[RetrievedArticleContext],
        language: str = "uz",
        mode: ResponseMode = "plain",
    ) -> GeneratedAnswer:
        # If no relevant articles retrieved, refuse safely
        if not contexts:
            refusal_text = REFUSAL_MESSAGES.get(language, REFUSAL_MESSAGES["uz"])
            return GeneratedAnswer(
                answer=refusal_text,
                citations=[],
                is_refusal=True,
                validation_passed=True,
                language=language,
                mode=mode,
            )

        system_prompt = build_system_prompt(language=language, mode=mode)
        if _has_curated_context(contexts):
            system_prompt = system_prompt + "\n\n" + CURATED_INSTRUCTION
        formatted_context = format_context_for_llm(contexts, language=language)

        user_content = (f"User Question: {query}\n\nRetrieved Legal Context:\n{formatted_context}\n\n"
                        f"{ANSWER_LANGUAGE_REMINDER.get(language, ANSWER_LANGUAGE_REMINDER['uz'])}")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        reasoning = _reasoning_options()

        raw_llm_response = await self.client.chat_completion(
            messages=messages,
            temperature=0.0,
            max_tokens=8192,
            reasoning=reasoning,
        )
        raw_llm_response = (raw_llm_response or "").strip()

        if not raw_llm_response or len(raw_llm_response) < 50:
            logger.warning("AnswerGenerator: primary LLM response was empty or too short. Attempting fallback model...")
            try:
                raw_llm_response = await self.client.chat_completion(
                    messages=messages,
                    model=self.client.fallback_model,
                    temperature=0.0,
                    max_tokens=8192,
                    reasoning=reasoning,
                )
                raw_llm_response = (raw_llm_response or "").strip()
            except Exception as e:
                logger.error(f"Fallback generation also failed: {e}")

        # Citation support check (manbaga solishtirish va tozalash) - disclaimer va validatsiyadan OLDIN
        support_warnings: List[str] = []
        if settings.SUPPORT_CHECK_ENABLED:
            raw_llm_response, support_warnings = await run_support_check(
                raw_answer=raw_llm_response,
                question=query,
                contexts=contexts,
                client=self.client,
                original_messages=messages,
                language=language,
                reasoning=reasoning,
            )

        # Attach disclaimer if not present
        disclaimer = DISCLAIMERS.get(language, DISCLAIMERS["uz"])
        if disclaimer.strip() not in raw_llm_response:
            raw_llm_response += disclaimer

        # Validation pass
        val_result: ValidationResult = CitationValidator.validate_and_sanitize(
            answer_text=raw_llm_response,
            retrieved_contexts=contexts,
            language=language,
        )

        all_warnings = list(val_result.warnings) + support_warnings

        return GeneratedAnswer(
            answer=val_result.sanitized_answer,
            clean_answer=val_result.clean_answer,
            telegram_formatted=val_result.telegram_formatted,
            citations=val_result.resolved_citations,
            is_refusal=val_result.is_refusal,
            validation_passed=val_result.is_valid,
            language=language,
            mode=mode,
            warnings=all_warnings,
        )

    async def generate_answer_stream(
        self,
        query: str,
        contexts: List[RetrievedArticleContext],
        language: str = "uz",
        mode: ResponseMode = "plain",
        status_warnings: Optional[List[dict]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streams generated text via SSE tokens, followed by a final JSON metadata event containing validated citations.

        NOTE: Support check (citation verification and regeneration) is intentionally NOT run in the streaming path
        because response tokens are already sent to the client in real time.
        """
        if not contexts:
            refusal = REFUSAL_MESSAGES.get(language, REFUSAL_MESSAGES["uz"])
            yield f"data: {json.dumps({'type': 'token', 'text': refusal})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'citations': [], 'is_refusal': True})}\n\n"
            return

        system_prompt = build_system_prompt(language=language, mode=mode)
        if _has_curated_context(contexts):
            system_prompt = system_prompt + "\n\n" + CURATED_INSTRUCTION
        formatted_context = format_context_for_llm(contexts, language=language)
        user_content = (f"User Question: {query}\n\nRetrieved Legal Context:\n{formatted_context}\n\n"
                        f"{ANSWER_LANGUAGE_REMINDER.get(language, ANSWER_LANGUAGE_REMINDER['uz'])}")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        reasoning = _reasoning_options()

        accumulated_chunks = []
        try:
            async for chunk in self.client.chat_completion_stream(
                messages,
                temperature=0.0,
                max_tokens=4000,
                reasoning=reasoning,
            ):
                accumulated_chunks.append(chunk)
                yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"
        except RuntimeError as e:
            logger.error(f"AnswerGenerator stream failed: {e}")
            error_payload = {
                "type": "error",
                "message": STREAM_ERROR_MESSAGES.get(language, STREAM_ERROR_MESSAGES["uz"]),
            }
            yield f"data: {json.dumps(error_payload)}\n\n"
            return

        full_raw_text = "".join(accumulated_chunks)
        disclaimer = DISCLAIMERS.get(language, DISCLAIMERS["uz"])
        if disclaimer.strip() not in full_raw_text:
            yield f"data: {json.dumps({'type': 'token', 'text': disclaimer})}\n\n"
            full_raw_text += disclaimer

        # Run validation
        val_result = CitationValidator.validate_and_sanitize(
            answer_text=full_raw_text,
            retrieved_contexts=contexts,
            language=language,
        )

        # Emit final structured payload. The streamed tokens are the raw model output (they may still contain
        # internal IDs), so the sanitized text is repeated here for clients that render the final answer.
        final_payload = {
            "type": "done",
            "citations": [c.model_dump() for c in val_result.resolved_citations],
            "is_refusal": val_result.is_refusal,
            "validation_passed": val_result.is_valid,
            "clean_answer": val_result.clean_answer or val_result.sanitized_answer,
            "telegram_formatted": val_result.telegram_formatted,
            "warnings": val_result.warnings,
            "status_warnings": status_warnings or [],
            "language": language,
            "mode": mode,
        }
        yield f"data: {json.dumps(final_payload)}\n\n"
