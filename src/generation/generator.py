import json
import logging
from typing import AsyncGenerator, Dict, List, Optional
from pydantic import BaseModel
from src.retrieval.reranker import RetrievedArticleContext
from src.clients.openrouter import OpenRouterClient
from src.generation.prompts import (
    build_system_prompt,
    format_context_for_llm,
    DISCLAIMERS,
    REFUSAL_MESSAGES,
    ResponseMode,
)
from src.generation.validator import CitationValidator, CitationItem, ValidationResult

logger = logging.getLogger(__name__)


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
        formatted_context = format_context_for_llm(contexts, language=language)

        user_content = f"User Question: {query}\n\nRetrieved Legal Context:\n{formatted_context}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        raw_llm_response = await self.client.chat_completion(
            messages=messages,
            temperature=0.0,
            max_tokens=8192,
        )
        raw_llm_response = (raw_llm_response or "").strip()

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

        return GeneratedAnswer(
            answer=val_result.sanitized_answer,
            clean_answer=val_result.clean_answer,
            telegram_formatted=val_result.telegram_formatted,
            citations=val_result.resolved_citations,
            is_refusal=val_result.is_refusal,
            validation_passed=val_result.is_valid,
            language=language,
            mode=mode,
            warnings=val_result.warnings,
        )

    async def generate_answer_stream(
        self,
        query: str,
        contexts: List[RetrievedArticleContext],
        language: str = "uz",
        mode: ResponseMode = "plain",
    ) -> AsyncGenerator[str, None]:
        """
        Streams generated text via SSE tokens, followed by a final JSON metadata event containing validated citations.
        """
        if not contexts:
            refusal = REFUSAL_MESSAGES.get(language, REFUSAL_MESSAGES["uz"])
            yield f"data: {json.dumps({'type': 'token', 'text': refusal})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'citations': [], 'is_refusal': True})}\n\n"
            return

        system_prompt = build_system_prompt(language=language, mode=mode)
        formatted_context = format_context_for_llm(contexts, language=language)
        user_content = f"User Question: {query}\n\nRetrieved Legal Context:\n{formatted_context}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        accumulated_chunks = []
        async for chunk in self.client.chat_completion_stream(messages, temperature=0.0, max_tokens=4000):
            accumulated_chunks.append(chunk)
            yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"

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

        # Emit final structured payload
        final_payload = {
            "type": "done",
            "citations": [c.model_dump() for c in val_result.resolved_citations],
            "is_refusal": val_result.is_refusal,
            "validation_passed": val_result.is_valid,
            "language": language,
            "mode": mode,
        }
        yield f"data: {json.dumps(final_payload)}\n\n"
