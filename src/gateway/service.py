import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional, Tuple
from fastapi import HTTPException
from pydantic import BaseModel, Field

from src.nlp.query_analyzer import QueryAnalysis, QueryAnalyzer
from src.retrieval.pipeline import retrieve_within
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
            optional=True,
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

# What every answering path asks of the retrieval and generation steps
RETRIEVAL_TOP_K = 40
RETRIEVAL_MAX_EXTRA = 8
RERANK_TOP_N = 8
SEMANTIC_CACHE_THRESHOLD = 0.95
MIN_CACHEABLE_CHARS = 80


def cache_keys(analysis, mode: str) -> tuple:
    """(language, mode) parts of the cache key. The script is part of the language part: the canonical query of a
    Cyrillic question equals its Latin transliteration, but their answers are written in different scripts. The
    answer version and the model are part of the mode part: a cached answer of an older pipeline is not served."""
    return (f"{analysis.detected_language}:{analysis.detected_script}",
            f"{mode}|{ANSWER_VERSION}|{settings.GENERATION_MODEL_PRIMARY}")


@dataclass
class _Question:
    """What the one-shot and the streaming path derive from a question before they diverge."""
    analysis: QueryAnalysis
    mode: str
    category: str
    groups_key: List[str]          # beneficiary groups of the question: a cached answer is reused only for the same ones
    asker: dict                    # generator argument when the client stated its own group
    has_filters: bool
    cache_text: str
    cache_lang: str
    cache_mode: str

    @property
    def language(self) -> str:
        return self.analysis.detected_language


def _analyse(question: str, language: str, mode: str, disability_group: str, category: str) -> _Question:
    """Sanitizes and analyzes the question. Pure: no store, cache or client is touched, so it can run before the language gate."""
    cleaned_query = sanitize_user_input(question)
    if not cleaned_query:
        raise HTTPException(status_code=422, detail="Savol matni bo'sh bo'lishi mumkin emas.")

    analysis = QueryAnalyzer.analyze(cleaned_query, user_language=None if language == "auto" else language)
    if disability_group not in ("all", "general"):
        if "general" in analysis.extracted_disability_types:
            analysis.extracted_disability_types.remove("general")
        if disability_group not in analysis.extracted_disability_types:
            analysis.extracted_disability_types.append(disability_group)
    has_filters = disability_group != "all" or category != "all"
    cache_lang, cache_mode = cache_keys(analysis, mode)
    return _Question(
        analysis=analysis,
        mode=mode,
        category=category,
        groups_key=sorted(analysis.extracted_disability_types),
        asker={"asker_group": disability_group} if disability_group not in ("all", "general") else {},
        has_filters=has_filters,
        cache_text=f"{cleaned_query} [{disability_group}|{category}]" if has_filters else cleaned_query,
        cache_lang=cache_lang,
        cache_mode=cache_mode,
    )


async def _lookup_cache(q: _Question, cache, client) -> Tuple[Optional[dict], Optional[List[float]], bool]:
    """
    (cached answer or None, the question's embedding or None, whether embeddings are available). The exact layer is asked
    first and a hit costs nothing else; only on a miss is the question embedded (a paid call) for the semantic layer
    and, later, for retrieval. The SQLite lookups run in worker threads: they must not stall the event loop.
    """
    hit = await asyncio.to_thread(cache.get, q.cache_text, q.cache_lang, q.cache_mode)
    if hit or client.is_mock:
        return hit, None, True
    try:
        vectors = await asyncio.wait_for(client.get_query_embeddings([q.analysis.normalized_query]),
                                         timeout=settings.QUERY_EMBED_TIMEOUT_S)
    except Exception as e:      # an error or asyncio.TimeoutError: full-text search only
        logger.warning(f"Error computing query vector for the semantic cache and retrieval: {e}")
        return None, None, False
    if not vectors:
        return None, None, True
    vector = vectors[0]
    try:
        hit = await asyncio.to_thread(
            cache.get_semantic, vector, q.cache_lang, q.cache_mode, threshold=SEMANTIC_CACHE_THRESHOLD,
            accept=lambda d: d.get("_groups") == q.groups_key and not q.has_filters and not d.get("_filtered"),
        )
    except Exception as e:
        logger.warning(f"Semantic cache lookup failed, answering without it: {e}")
        hit = None
    return hit, vector, True


def _result_from_cache(hit: dict, q: _Question) -> AnswerResult:
    text = hit.get("clean_answer") or hit.get("answer", "")
    return AnswerResult(
        answer=text,
        clean_answer=text,
        telegram_formatted=hit.get("telegram_formatted") or hit.get("answer", ""),
        citations=[CitationItem(**c) if isinstance(c, dict) else c for c in hit.get("citations", [])],
        detected_language=hit.get("detected_language", q.language),
        detected_script=hit.get("detected_script", q.analysis.detected_script),
        mode=q.mode,
        is_refusal=hit.get("is_refusal", False),
        validation_passed=hit.get("validation_passed", True),
        status_warnings=hit.get("status_warnings", []),
        cached=True,
        cache_type=hit.get("cache_type", "exact"),
        semantic_similarity=hit.get("semantic_similarity"),
        retrieval_confidence=hit.get("retrieval_confidence"),
    )


def _is_cacheable(result: AnswerResult) -> bool:
    """Caching rules: verified, substantive, non-refusal, really generated."""
    return (
        result.validation_passed
        and not result.is_refusal
        and not result.degraded
        and len((result.clean_answer or result.answer).strip()) > MIN_CACHEABLE_CHARS
    )


async def _cache_answer(q: _Question, cache, query_vector: Optional[List[float]], result: AnswerResult) -> None:
    if not _is_cacheable(result):
        return
    data = result.model_dump()
    data["_groups"] = q.groups_key
    data["_filtered"] = q.has_filters
    await asyncio.to_thread(cache.set, q.cache_text, q.cache_lang, q.cache_mode, data, query_vector)


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
    2. Analyze query language (uz, ru or en: the answer is written in it), script, and disability domain
    3. Check Layer 1 (exact cache) and Layer 2 (semantic cache)
    4. Hybrid retrieval, expansion, rerank, and relevance gating
    5. Anti-hallucination generation and citation validation
    6. Cache substantive verified answers
    """
    q = _analyse(question, language, mode, disability_group, category)

    from src.api.app import get_store, get_cache, get_client
    store = get_store()
    cache = get_cache()
    client = get_client()

    hit, query_vector, embedding_available = await _lookup_cache(q, cache, client)
    if hit:
        return _result_from_cache(hit, q)

    if not generation_budget.consume():
        raise HTTPException(status_code=429, detail=DAILY_LIMIT_MESSAGE)

    retrieval = await retrieve_within(
        settings.RETRIEVAL_TIMEOUT_S,
        analysis=q.analysis,
        store=store,
        client=client,
        top_k=RETRIEVAL_TOP_K,
        max_extra=RETRIEVAL_MAX_EXTRA,
        rerank_top_n=RERANK_TOP_N,
        query_vector=query_vector,
        use_vector=embedding_available,
        category=q.category,
    )

    generator = AnswerGenerator(client=client)
    cleaned_query = q.analysis.raw_query
    try:
        try:
            gen_result = await asyncio.wait_for(
                generator.generate_answer(
                    query=cleaned_query,
                    contexts=retrieval.contexts,
                    language=q.language,
                    mode=mode,
                    **q.asker,
                ),
                timeout=settings.ANSWER_TIMEOUT_S,
            )
        except asyncio.TimeoutError:      # a hung provider must not hold the request: the matching norms are shown
            logger.error(f"Answer generation exceeded {settings.ANSWER_TIMEOUT_S}s; serving the matching norms only")
            gen_result = generator.degraded_answer(retrieval.contexts, q.language, mode, cleaned_query)
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
        detected_language=q.language,
        detected_script=q.analysis.detected_script,
        mode=mode,
        is_refusal=gen_result.is_refusal,
        validation_passed=gen_result.validation_passed,
        status_warnings=retrieval.status_warnings,
        cached=False,
        retrieval_confidence=round(retrieval.decision.confidence, 3) if retrieval.decision else None,
        warnings=gen_result.warnings,
        degraded=gen_result.degraded,
    )
    await _cache_answer(q, cache, query_vector, result)
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


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


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
    q = _analyse(question, language, mode, disability_group, category)

    from src.api.app import get_store, get_cache, get_client
    store = get_store()
    cache = get_cache()
    client = get_client()

    # Same two cache layers as answer_question; a hit is replayed as one token event plus the final event
    hit, query_vector, embedding_available = await _lookup_cache(q, cache, client)
    if hit:
        cached = _result_from_cache(hit, q)
        yield _sse({"type": "token", "text": cached.clean_answer})
        yield _sse({
            "type": "done",
            "citations": [c.model_dump() for c in cached.citations],
            "is_refusal": cached.is_refusal,
            "validation_passed": cached.validation_passed,
            "clean_answer": cached.clean_answer,
            "telegram_formatted": cached.telegram_formatted or cached.clean_answer,
            "warnings": hit.get("warnings", []),
            "status_warnings": cached.status_warnings,
            "language": q.language,
            "mode": mode,
            "cached": True,
            "cache_type": cached.cache_type,
        })
        return

    if not generation_budget.consume():
        yield _sse({"type": "error", "message": DAILY_LIMIT_MESSAGE})
        return

    retrieval = await retrieve_within(
        settings.RETRIEVAL_TIMEOUT_S,
        analysis=q.analysis,
        store=store,
        client=client,
        top_k=RETRIEVAL_TOP_K,
        max_extra=RETRIEVAL_MAX_EXTRA,
        rerank_top_n=RERANK_TOP_N,
        query_vector=query_vector,
        use_vector=embedding_available,
        category=q.category,
    )

    generator = AnswerGenerator(client=client)
    final_event = None
    async for sse_chunk in generator.generate_answer_stream(
        query=q.analysis.raw_query,
        contexts=retrieval.contexts,
        language=q.language,
        mode=mode,
        status_warnings=retrieval.status_warnings,
        **q.asker,
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

    if final_event:
        try:
            text = (final_event.get("clean_answer") or "").strip()
            result = AnswerResult(
                answer=text,
                clean_answer=text,
                telegram_formatted=final_event.get("telegram_formatted") or text,
                citations=[CitationItem(**c) for c in final_event.get("citations", [])],
                detected_language=q.language,
                detected_script=q.analysis.detected_script,
                mode=mode,
                is_refusal=bool(final_event.get("is_refusal", False)),
                validation_passed=bool(final_event.get("validation_passed", False)),
                status_warnings=final_event.get("status_warnings", []),
                cached=False,
                retrieval_confidence=round(retrieval.decision.confidence, 3) if retrieval.decision else None,
                warnings=final_event.get("warnings", []),
                degraded=bool(final_event.get("degraded", False)),
            )
            await _cache_answer(q, cache, query_vector, result)
        except Exception:
            logger.warning("Could not cache a streamed answer", exc_info=True)
