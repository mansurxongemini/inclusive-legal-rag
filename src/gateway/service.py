import asyncio
import json
import logging
from typing import AsyncGenerator, List, Optional
from fastapi import HTTPException
from pydantic import BaseModel, Field

from src.nlp.query_analyzer import QueryAnalyzer
from src.retrieval.pipeline import retrieve_contexts
from src.config import settings
from src.api.middleware.hardening import generation_budget
from src.generation.generator import AnswerGenerator
from src.generation.prompts import ANSWER_VERSION
from src.generation.validator import CitationItem
from src.api.middleware.security import sanitize_user_input

from src.clients.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)


async def condense_question(history, question: str, client: Optional[OpenRouterClient] = None) -> str:
    """
    Rewrites a follow-up question into a standalone question in the user's language using OpenRouter.
    Only called when history exists; on any error or in mock mode returns the original question.
    """
    if not history or not question or not question.strip():
        return question

    if client is None:
        from src.api.app import get_client
        client = get_client()

    if getattr(client, "is_mock", False):
        return question

    formatted_turns = []
    for item in history:
        if hasattr(item, "question") and hasattr(item, "answer"):
            formatted_turns.append(f"Foydalanuvchi: {item.question}\nYordamchi: {item.answer[:400]}")
        elif isinstance(item, dict):
            if "question" in item and "answer" in item:
                formatted_turns.append(f"Foydalanuvchi: {item['question']}\nYordamchi: {str(item['answer'])[:400]}")
            elif item.get("role") in ("user", "assistant"):
                role_label = "Foydalanuvchi" if item["role"] == "user" else "Yordamchi"
                formatted_turns.append(f"{role_label}: {str(item.get('content', ''))[:400]}")

    if not formatted_turns:
        return question

    history_text = "\n\n".join(formatted_turns)
    system_prompt = (
        "Siz O'zbekiston qonunchiligi bo'yicha yordamchisiz. Oldingi suhbat konteksti va foydalanuvchining yangi savoli berilgan.\n"
        "Vazifangiz: Yangi savol agar oldingi suhbatga bog'liq bo'lsa (masalan olmoshlar yoki qisqa iboralar ishlatilgan bo'lsa), "
        "uni suhbat tarixiga tayanmagan holda mustaqil tushunarli bo'lgan yagona to'liq yuridik savolga aylantiring.\n"
        "Savol foydalanuvchi bergan tilda bo'lishi shart.\n"
        "Agar savol allaqachon to'liq va mustaqil bo'lsa, uni o'zgarishsiz qoldiring.\n"
        "Faqat va faqat qayta shakllantirilgan savol matnini chiqaring. Hech qanday sharh yoki qo'shimcha so'z yozmang."
    )
    user_prompt = f"Suhbat tarixi:\n{history_text}\n\nYangi savol: {question}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = await client.chat_completion(
            messages=messages,
            temperature=0.0,
            max_tokens=300,
            min_chars=2,
            reasoning={"enabled": False},
            light=True,
        )
        if not raw:
            return question
        rewritten = raw.strip().strip('"\'`«»').strip()
        if not rewritten or len(rewritten) > 3 * len(question) + 200:
            return question
        return rewritten
    except Exception as e:
        logger.warning(f"condense_question failed, using original: {e}")
        return question



class AnswerResult(BaseModel):
    answer: str
    clean_answer: str = ""
    telegram_formatted: str = ""
    citations: List[CitationItem] = Field(default_factory=list)
    detected_language: str = "uz"
    detected_script: str = "latn"
    mode: str = "plain"
    is_refusal: bool = False
    validation_passed: bool = True
    status_warnings: List[dict] = Field(default_factory=list)
    cached: bool = False
    cache_type: Optional[str] = None
    semantic_similarity: Optional[float] = None
    retrieval_confidence: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)
    degraded: bool = False

DAILY_LIMIT_MESSAGE = "Bugungi javoblar chegarasi tugadi. Iltimos, ertaga qayta urinib ko'ring yoki vakolatli organga murojaat qiling."


def cache_keys(analysis, mode: str) -> tuple:
    """(language, mode) parts of the cache key. The script is part of the language part: the canonical query of a
    Cyrillic question equals its Latin transliteration, but their answers are written in different scripts. The
    answer version and the model are part of the mode part: a cached answer of an older pipeline is not served."""
    return (f"{analysis.detected_language}:{analysis.detected_script}",
            f"{mode}|{ANSWER_VERSION}|{settings.GENERATION_MODEL_PRIMARY}")


async def answer_question(
    question: str,
    *,
    language: str = "auto",
    mode: str = "plain",
    disability_group: str = "all",
    category: str = "all",
) -> AnswerResult:
    """
    Core answering pipeline for legal questions:
    1. Sanitize user input against injection
    2. Analyze query language, script, and disability domain
    3. Check Layer 1 (exact cache) and Layer 2 (semantic cache)
    4. Hybrid retrieval, expansion, rerank, and relevance gating
    5. Anti-hallucination generation and citation validation
    6. Cache substantive verified answers
    """
    cleaned_query = sanitize_user_input(question)
    if not cleaned_query:
        raise HTTPException(status_code=422, detail="Savol matni bo'sh bo'lishi mumkin emas.")

    from src.api.app import get_store, get_cache, get_client
    store = get_store()
    cache = get_cache()
    client = get_client()

    # Query analysis
    user_lang = None if language == "auto" else language
    analysis = QueryAnalyzer.analyze(cleaned_query, user_language=user_lang)
    target_language = analysis.detected_language

    if disability_group not in ("all", "general"):
        if "general" in analysis.extracted_disability_types:
            analysis.extracted_disability_types.remove("general")
        if disability_group not in analysis.extracted_disability_types:
            analysis.extracted_disability_types.append(disability_group)
    groups_key = sorted(analysis.extracted_disability_types)
    asker = {"asker_group": disability_group} if disability_group not in ("all", "general") else {}
    has_filters = disability_group != "all" or category != "all"
    cache_text = f"{cleaned_query} [{disability_group}|{category}]" if has_filters else cleaned_query

    # Exact cache check
    cache_lang, cache_mode = cache_keys(analysis, mode)
    cached_resp = cache.get(cache_text, cache_lang, cache_mode)
    if cached_resp:
        return AnswerResult(
            answer=cached_resp.get("clean_answer") or cached_resp.get("answer", ""),
            clean_answer=cached_resp.get("clean_answer") or cached_resp.get("answer", ""),
            telegram_formatted=cached_resp.get("telegram_formatted") or cached_resp.get("answer", ""),
            citations=[CitationItem(**c) if isinstance(c, dict) else c for c in cached_resp.get("citations", [])],
            detected_language=cached_resp.get("detected_language", target_language),
            detected_script=cached_resp.get("detected_script", analysis.detected_script),
            mode=mode,
            is_refusal=cached_resp.get("is_refusal", False),
            validation_passed=cached_resp.get("validation_passed", True),
            status_warnings=cached_resp.get("status_warnings", []),
            cached=True,
            cache_type=cached_resp.get("cache_type", "exact"),
            semantic_similarity=cached_resp.get("semantic_similarity"),
            retrieval_confidence=cached_resp.get("retrieval_confidence"),
        )

    # Compute dense vector
    query_vector = None
    embedding_available = True
    if not client.is_mock:
        try:
            q_vectors = await client.get_embeddings([analysis.normalized_query])
            if q_vectors:
                query_vector = q_vectors[0]
                sem_cached = cache.get_semantic(
                    query_vector,
                    cache_lang,
                    cache_mode,
                    threshold=0.95,
                    accept=lambda d: d.get("_groups") == groups_key and not has_filters and not d.get("_filtered"),
                )
                if sem_cached:
                    return AnswerResult(
                        answer=sem_cached.get("clean_answer") or sem_cached.get("answer", ""),
                        clean_answer=sem_cached.get("clean_answer") or sem_cached.get("answer", ""),
                        telegram_formatted=sem_cached.get("telegram_formatted") or sem_cached.get("answer", ""),
                        citations=[CitationItem(**c) if isinstance(c, dict) else c for c in sem_cached.get("citations", [])],
                        detected_language=sem_cached.get("detected_language", target_language),
                        detected_script=sem_cached.get("detected_script", analysis.detected_script),
                        mode=mode,
                        is_refusal=sem_cached.get("is_refusal", False),
                        validation_passed=sem_cached.get("validation_passed", True),
                        status_warnings=sem_cached.get("status_warnings", []),
                        cached=True,
                        cache_type="semantic",
                        semantic_similarity=sem_cached.get("semantic_similarity"),
                        retrieval_confidence=sem_cached.get("retrieval_confidence"),
                    )
        except Exception as e:
            embedding_available = False
            logger.warning(f"Error computing query vector for semantic cache: {e}")

    if not generation_budget.consume():
        raise HTTPException(status_code=429, detail=DAILY_LIMIT_MESSAGE)

    # Retrieval
    retrieval = await retrieve_contexts(
        analysis=analysis,
        store=store,
        client=client,
        top_k=40,
        max_extra=8,
        rerank_top_n=8,
        query_vector=query_vector,
        use_vector=embedding_available,
        category=category,
    )
    final_contexts = retrieval.contexts
    status_warnings = retrieval.status_warnings

    # Generation
    generator = AnswerGenerator(client=client)
    try:
        try:
            gen_result = await asyncio.wait_for(
                generator.generate_answer(
                    query=cleaned_query,
                    contexts=final_contexts,
                    language=target_language,
                    mode=mode,
                    **asker,
                ),
                timeout=settings.ANSWER_TIMEOUT_S,
            )
        except asyncio.TimeoutError:      # a hung provider must not hold the request: the matching norms are shown
            logger.error(f"Answer generation exceeded {settings.ANSWER_TIMEOUT_S}s; serving the matching norms only")
            gen_result = generator._degraded_answer(final_contexts, target_language, mode, cleaned_query)
    except RuntimeError as e:
        logger.error(f"Answer generation unavailable: {e}")
        raise HTTPException(
            status_code=503,
            detail="Javob yaratish xizmati vaqtincha mavjud emas. Iltimos, birozdan so'ng qayta urinib ko'ring.",
        )

    res_answer = gen_result.clean_answer or gen_result.answer
    result = AnswerResult(
        answer=res_answer,
        clean_answer=res_answer,
        telegram_formatted=gen_result.telegram_formatted or gen_result.answer,
        citations=gen_result.citations,
        detected_language=target_language,
        detected_script=analysis.detected_script,
        mode=mode,
        is_refusal=gen_result.is_refusal,
        validation_passed=gen_result.validation_passed,
        status_warnings=status_warnings,
        cached=False,
        retrieval_confidence=round(retrieval.decision.confidence, 3) if retrieval.decision else None,
        warnings=gen_result.warnings,
        degraded=gen_result.degraded,
    )

    # Caching rules: verified, substantive, non-refusal, really generated
    if (
        result.validation_passed
        and not result.is_refusal
        and not result.degraded
        and len((result.clean_answer or result.answer).strip()) > 80
    ):
        cached_data = result.model_dump()
        cached_data["_groups"] = groups_key
        cached_data["_filtered"] = has_filters
        cache.set(cache_text, cache_lang, cache_mode, cached_data, vector=query_vector)

    return result


async def answer_question_stream_events(
    question: str,
    *,
    language: str = "auto",
    mode: str = "plain",
    disability_group: str = "all",
    category: str = "all",
) -> AsyncGenerator[dict, None]:
    """
    The events of answer_question_stream as dicts:
    {'type': 'token', 'text': ...} | {'type': 'error', 'message': ...} | {'type': 'done', 'citations': [...], ...}
    """
    async for raw_sse in answer_question_stream(
        question, language=language, mode=mode, disability_group=disability_group, category=category,
    ):
        trimmed = raw_sse.strip()
        if trimmed.startswith("data: "):
            try:
                yield json.loads(trimmed[6:].strip())
            except json.JSONDecodeError:
                pass


async def answer_question_stream(
    question: str,
    *,
    language: str = "auto",
    mode: str = "plain",
    disability_group: str = "all",
    category: str = "all",
) -> AsyncGenerator[str, None]:
    """
    Streaming variant of answer_question yielding raw SSE text formatted as:
    `data: {"type": "token", "text": "..."}\n\n`
    `data: {"type": "done", ...}\n\n`
    Directly compatible with existing /api/v1/query?stream=true behavior.
    """
    cleaned_query = sanitize_user_input(question)
    if not cleaned_query:
        raise HTTPException(status_code=422, detail="Savol matni bo'sh bo'lishi mumkin emas.")

    from src.api.app import get_store, get_cache, get_client
    store = get_store()
    cache = get_cache()
    client = get_client()

    user_lang = None if language == "auto" else language
    analysis = QueryAnalyzer.analyze(cleaned_query, user_language=user_lang)
    target_language = analysis.detected_language

    if disability_group not in ("all", "general"):
        if "general" in analysis.extracted_disability_types:
            analysis.extracted_disability_types.remove("general")
        if disability_group not in analysis.extracted_disability_types:
            analysis.extracted_disability_types.append(disability_group)
    groups_key = sorted(analysis.extracted_disability_types)
    asker = {"asker_group": disability_group} if disability_group not in ("all", "general") else {}
    has_filters = disability_group != "all" or category != "all"
    cache_text = f"{cleaned_query} [{disability_group}|{category}]" if has_filters else cleaned_query

    # Same two cache layers as answer_question; a hit is replayed as one token event plus the final event
    cache_lang, cache_mode = cache_keys(analysis, mode)
    cached = cache.get(cache_text, cache_lang, cache_mode)
    cache_type = "exact"
    query_vector = None
    embedding_available = True
    if not client.is_mock:
        try:
            q_vectors = await client.get_embeddings([analysis.normalized_query])
            if q_vectors:
                query_vector = q_vectors[0]
                if not cached:
                    cached = cache.get_semantic(
                        query_vector,
                        cache_lang,
                        cache_mode,
                        threshold=0.95,
                        accept=lambda d: d.get("_groups") == groups_key and not has_filters and not d.get("_filtered"),
                    )
                    cache_type = "semantic"
        except Exception as e:
            embedding_available = False
            logger.warning(f"Error computing query vector for streaming retrieval: {e}")

    if cached:
        text = cached.get("clean_answer") or cached.get("answer", "")
        yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"
        done = {
            "type": "done",
            "citations": cached.get("citations", []),
            "is_refusal": cached.get("is_refusal", False),
            "validation_passed": cached.get("validation_passed", True),
            "clean_answer": text,
            "telegram_formatted": cached.get("telegram_formatted") or text,
            "warnings": cached.get("warnings", []),
            "status_warnings": cached.get("status_warnings", []),
            "language": target_language,
            "mode": mode,
            "cached": True,
            "cache_type": cached.get("cache_type", cache_type),
        }
        yield f"data: {json.dumps(done)}\n\n"
        return

    if not generation_budget.consume():
        yield f"data: {json.dumps({'type': 'error', 'message': DAILY_LIMIT_MESSAGE})}\n\n"
        return

    retrieval = await retrieve_contexts(
        analysis=analysis,
        store=store,
        client=client,
        top_k=40,
        max_extra=8,
        rerank_top_n=8,
        query_vector=query_vector,
        use_vector=embedding_available,
        category=category,
    )
    final_contexts = retrieval.contexts
    status_warnings = retrieval.status_warnings

    generator = AnswerGenerator(client=client)
    final_event = None
    async for sse_chunk in generator.generate_answer_stream(
        query=cleaned_query,
        contexts=final_contexts,
        language=target_language,
        mode=mode,
        status_warnings=status_warnings,
        **asker,
    ):
        yield sse_chunk
        trimmed = sse_chunk.strip()
        if trimmed.startswith("data: "):
            try:
                event = json.loads(trimmed[6:])
            except json.JSONDecodeError:
                continue
            if event.get("type") == "done":
                final_event = event

    # Caching rules: verified, substantive, non-refusal (as in answer_question)
    if final_event:
        text = (final_event.get("clean_answer") or "").strip()
        if (final_event.get("validation_passed") and not final_event.get("is_refusal")
                and not final_event.get("degraded") and len(text) > 80):
            try:
                result = AnswerResult(
                    answer=text,
                    clean_answer=text,
                    telegram_formatted=final_event.get("telegram_formatted") or text,
                    citations=[CitationItem(**c) for c in final_event.get("citations", [])],
                    detected_language=target_language,
                    detected_script=analysis.detected_script,
                    mode=mode,
                    is_refusal=False,
                    validation_passed=True,
                    status_warnings=final_event.get("status_warnings", []),
                    cached=False,
                    retrieval_confidence=round(retrieval.decision.confidence, 3) if retrieval.decision else None,
                    warnings=final_event.get("warnings", []),
                )
                data = result.model_dump()
                data["_groups"] = groups_key
                data["_filtered"] = has_filters
                cache.set(cache_text, cache_lang, cache_mode, data, vector=query_vector)
            except Exception:
                logger.warning("Could not cache a streamed answer", exc_info=True)
