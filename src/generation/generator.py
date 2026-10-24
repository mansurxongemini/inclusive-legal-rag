import json
import logging
from typing import AsyncGenerator, Dict, List, Optional, Tuple
from pydantic import BaseModel
from src.config import settings
from src.retrieval.reranker import RetrievedArticleContext
from src.clients.openrouter import OpenRouterClient
from src.generation.prompts import (
    build_system_prompt,
    build_user_content,
    format_context_for_llm,
    CURATED_INSTRUCTION,
    disclaimer_for,
    refusal_for,
    ResponseMode,
)
from src.generation.degraded import sources_only_text
from src.generation.guards import guard_answer


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
    degraded: bool = False          # no generation model was reachable: the text is a quotation of the matching norms


# An answer is 120-230 words; this bound only stops a model that loops (one run repeated a sentence 108 times).
# Reasoning tokens share the budget, so the tight bound applies only when reasoning is switched off.
MAX_ANSWER_TOKENS = 2048
MAX_ANSWER_TOKENS_WITH_REASONING = 8192


def _max_answer_tokens() -> int:
    effort = (settings.GENERATION_REASONING_EFFORT or "").strip().lower()
    return MAX_ANSWER_TOKENS if effort == "none" else MAX_ANSWER_TOKENS_WITH_REASONING


def attach_disclaimer(val: ValidationResult, disclaimer: str, already_present: bool) -> Tuple[str, str, str]:
    """(answer, clean_answer, telegram_formatted) with the disclaimer after the answer and before the source footer."""
    if already_present:
        return val.sanitized_answer, val.clean_answer, val.telegram_formatted
    clean = val.clean_answer
    footer = val.telegram_formatted[len(clean):] if val.telegram_formatted.startswith(clean) else ""
    return (
        val.sanitized_answer.rstrip() + disclaimer,
        clean.rstrip() + disclaimer,
        clean.rstrip() + disclaimer + footer,
    )


class AnswerGenerator:
    """
    Coordinates answer generation via OpenRouter with anti-hallucination guardrails and validation.
    """

    def __init__(self, client: Optional[OpenRouterClient] = None):
        self.client = client or OpenRouterClient()

    def _messages(self, query, contexts, language, mode, asker_group: str = ""):
        system_prompt = build_system_prompt(language=language, mode=mode)
        if _has_curated_context(contexts):
            system_prompt = system_prompt + "\n\n" + CURATED_INSTRUCTION
        formatted_context = format_context_for_llm(contexts, language=language)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_content(query, formatted_context, language, asker_group)},
        ]

    async def _post_process(self, messages, raw: str, query: str, contexts, language: str, reasoning) -> Tuple[str, List[str]]:
        """Support check (when enabled), then the deterministic guards with one repair round. Never raises."""
        warnings: List[str] = []
        text = raw
        if settings.SUPPORT_CHECK_ENABLED:
            text, support_warnings = await run_support_check(
                raw_answer=text, question=query, contexts=contexts, client=self.client,
                original_messages=messages, language=language, reasoning=reasoning,
            )
            warnings += support_warnings
        try:
            text, guard_warnings = await guard_answer(
                self.client, messages, text, query, contexts, language, reasoning=reasoning,
                max_tokens=_max_answer_tokens(),
            )
            warnings += guard_warnings
        except Exception as e:  # a guard must never cost the user the answer
            logger.warning(f"answer guards failed: {type(e).__name__}: {e}")
        return text, warnings

    def _finish(self, raw: str, contexts, language: str, mode, warnings: List[str], query: str = "", degraded: bool = False):
        """Validation, disclaimer and the response record for a finished answer text."""
        val_result: ValidationResult = CitationValidator.validate_and_sanitize(
            answer_text=raw, retrieved_contexts=contexts, language=language,
        )
        disclaimer = disclaimer_for(language, query)
        answer_text, clean_text, telegram_text = attach_disclaimer(
            val_result, disclaimer, already_present=disclaimer.strip() in raw,
        )
        return val_result, GeneratedAnswer(
            answer=answer_text,
            clean_answer=clean_text,
            telegram_formatted=telegram_text,
            citations=val_result.resolved_citations,
            is_refusal=val_result.is_refusal,
            validation_passed=val_result.is_valid,
            language=language,
            mode=mode,
            warnings=list(val_result.warnings) + warnings,
            degraded=degraded,
        )

    def degraded_answer(self, contexts, language: str, mode, query: str = "") -> GeneratedAnswer:
        _, result = self._finish(sources_only_text(contexts, language, query=query), contexts, language, mode,
                                 ["llm_unavailable: sources only, no generated text"], query, degraded=True)
        return result

    async def generate_answer(
        self,
        query: str,
        contexts: List[RetrievedArticleContext],
        language: str = "uz",
        mode: ResponseMode = "plain",
        asker_group: str = "",
    ) -> GeneratedAnswer:
        # If no relevant articles retrieved, refuse safely
        if not contexts:
            refusal_text = refusal_for(language, query)
            return GeneratedAnswer(
                answer=refusal_text,
                citations=[],
                is_refusal=True,
                validation_passed=True,
                language=language,
                mode=mode,
            )

        messages = self._messages(query, contexts, language, mode, asker_group)
        reasoning = _reasoning_options()

        try:
            raw_llm_response = await self.client.chat_completion(
                messages=messages,
                temperature=0.0,
                max_tokens=_max_answer_tokens(),
                reasoning=reasoning,
            )
            raw_llm_response = (raw_llm_response or "").strip()
        except RuntimeError as e:
            logger.error(f"AnswerGenerator: no generation model available, serving the matching norms only: {e}")
            return self.degraded_answer(contexts, language, mode, query)

        raw_llm_response, post_warnings = await self._post_process(
            messages, raw_llm_response, query, contexts, language, reasoning)
        _, result = self._finish(raw_llm_response, contexts, language, mode, post_warnings, query)
        return result

    async def generate_answer_stream(
        self,
        query: str,
        contexts: List[RetrievedArticleContext],
        language: str = "uz",
        mode: ResponseMode = "plain",
        status_warnings: Optional[List[dict]] = None,
        asker_group: str = "",
    ) -> AsyncGenerator[str, None]:
        """
        Streams generated text as SSE `token` events, then verifies the finished answer (support check, script, numbers
        and wording guards) and sends one `done` event whose `clean_answer` is the verified text with the numbered
        citations. Clients must show `clean_answer` as the answer: the streamed tokens are the raw model output (they
        may still contain internal ids, and a repaired answer replaces them).
        """
        if not contexts:
            refusal = refusal_for(language, query)
            yield f"data: {json.dumps({'type': 'token', 'text': refusal})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'citations': [], 'is_refusal': True})}\n\n"
            return

        messages = self._messages(query, contexts, language, mode, asker_group)
        reasoning = _reasoning_options()

        accumulated_chunks = []
        try:
            async for chunk in self.client.chat_completion_stream(
                messages,
                temperature=0.0,
                max_tokens=_max_answer_tokens(),
                reasoning=reasoning,
            ):
                accumulated_chunks.append(chunk)
                yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"
        except RuntimeError as e:
            logger.error(f"AnswerGenerator stream failed: {e}")
            if accumulated_chunks:      # tokens already reached the client: no second answer can follow
                error_payload = {
                    "type": "error",
                    "message": STREAM_ERROR_MESSAGES.get(language, STREAM_ERROR_MESSAGES["uz"]),
                }
                yield f"data: {json.dumps(error_payload)}\n\n"
                return
            degraded = self.degraded_answer(contexts, language, mode, query)
            yield f"data: {json.dumps({'type': 'token', 'text': degraded.clean_answer})}\n\n"
            yield f"data: {json.dumps(self._done_payload(degraded, status_warnings))}\n\n"
            return

        full_raw_text = "".join(accumulated_chunks)
        yield f"data: {json.dumps({'type': 'status', 'stage': 'verifying'})}\n\n"
        verified_text, post_warnings = await self._post_process(
            messages, full_raw_text, query, contexts, language, reasoning)
        disclaimer = disclaimer_for(language, query)
        if disclaimer.strip() not in verified_text:
            yield f"data: {json.dumps({'type': 'token', 'text': disclaimer})}\n\n"

        _, result = self._finish(verified_text, contexts, language, mode, post_warnings, query)
        yield f"data: {json.dumps(self._done_payload(result, status_warnings))}\n\n"

    @staticmethod
    def _done_payload(result: GeneratedAnswer, status_warnings: Optional[List[dict]]) -> dict:
        return {
            "type": "done",
            "citations": [c.model_dump() for c in result.citations],
            "is_refusal": result.is_refusal,
            "validation_passed": result.validation_passed,
            "clean_answer": result.clean_answer or result.answer,
            "telegram_formatted": result.telegram_formatted,
            "warnings": result.warnings,
            "degraded": result.degraded,
            "status_warnings": status_warnings or [],
            "language": result.language,
            "mode": result.mode,
        }
