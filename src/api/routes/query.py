import json
import logging
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.domain.disability_taxonomy import CATEGORY_IDS, DISABILITY_GROUPS

from src.nlp.query_analyzer import QueryAnalyzer, SupportedLanguage
from src.retrieval.pipeline import retrieve_contexts
from src.generation.generator import AnswerGenerator
from src.generation.validator import CitationItem
from src.api.middleware.security import sanitize_user_input
from src.api.middleware.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Query"])


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000, description="Legal question from citizen or reviewer")
    language: Literal["auto", "uz", "ru", "en"] = Field(default="auto", description="Preferred response language")
    mode: Literal["plain", "legal_text", "easy_read", "subsumption"] = Field(default="plain", description="plain language summary, verbatim legal text, easy-read, or structured analysis")
    conversation_id: Optional[str] = Field(default=None, max_length=128, description="Optional conversation trace ID")
    disability_group: str = Field(default="all", description="Beneficiary group to prioritize (see /api/v1/inclusive/categories)")
    category: str = Field(default="all", description="Legal domain filter (see /api/v1/inclusive/categories)")

    @field_validator("disability_group")
    @classmethod
    def _check_group(cls, v: str) -> str:
        allowed = {"all", "general", *(g.id for g in DISABILITY_GROUPS)}
        if v not in allowed:
            raise ValueError(f"disability_group must be one of {sorted(allowed)}")
        return v

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        if v != "all" and v not in CATEGORY_IDS:
            raise ValueError(f"category must be 'all' or one of {CATEGORY_IDS}")
        return v


class QueryResponse(BaseModel):
    answer: str
    clean_answer: str = ""
    telegram_formatted: str = ""
    citations: List[CitationItem]
    detected_language: str
    detected_script: str
    mode: str
    is_refusal: bool
    validation_passed: bool
    status_warnings: List[dict] = []
    conversation_id: Optional[str] = None
    cached: bool = False
    cache_type: Optional[str] = None
    semantic_similarity: Optional[float] = None
    retrieval_confidence: Optional[float] = None


@router.post("/query", response_model=QueryResponse)
async def query_legal_rag(
    request: Request,
    payload: QueryRequest,
    stream: bool = Query(default=False, description="Stream response tokens via SSE"),
):
    # 1. Rate limiting check
    rate_limiter.check(request)

    # 2. Sanitize input against prompt injection
    cleaned_query = sanitize_user_input(payload.question)
    if not cleaned_query:
        raise HTTPException(status_code=422, detail="Savol matni bo'sh bo'lishi mumkin emas.")

    from src.api.app import get_store, get_cache, get_client
    store = get_store()
    cache = get_cache()
    client = get_client()

    # 3. Query analysis: detect language and script, normalize Cyrillic -> Latin if Uzbek
    user_lang = None if payload.language == "auto" else payload.language
    analysis = QueryAnalyzer.analyze(cleaned_query, user_language=user_lang)
    target_language = analysis.detected_language

    # An explicit beneficiary group refines the detected ones
    if payload.disability_group not in ("all", "general"):
        if "general" in analysis.extracted_disability_types:
            analysis.extracted_disability_types.remove("general")
        if payload.disability_group not in analysis.extracted_disability_types:
            analysis.extracted_disability_types.append(payload.disability_group)
    groups_key = sorted(analysis.extracted_disability_types)
    has_filters = payload.disability_group != "all" or payload.category != "all"
    cache_text = f"{cleaned_query} [{payload.disability_group}|{payload.category}]" if has_filters else cleaned_query

    # 4. Check Layer 1: Canonical Normalized Query Cache (0.1ms)
    if not stream:
        cached_resp = cache.get(cache_text, target_language, payload.mode)
        if cached_resp:
            cached_resp["cached"] = True
            return cached_resp

    # Compute dense query vector for semantic cache check and retrieval
    query_vector = None
    embedding_available = True
    if not client.is_mock:
        try:
            q_vectors = await client.get_embeddings([analysis.normalized_query])
            if q_vectors:
                query_vector = q_vectors[0]
                # Check Layer 2: Semantic Vector Cache (similarity >= 93%)
                if not stream:
                    sem_cached = cache.get_semantic(
                        query_vector, target_language, payload.mode, threshold=0.95,
                        accept=lambda d: d.get("_groups") == groups_key and not has_filters and not d.get("_filtered"),
                    )
                    if sem_cached:
                        sem_cached["cached"] = True
                        return sem_cached
        except Exception as e:
            embedding_available = False
            logger.warning(f"Error computing query vector for semantic cache: {e}")

    # 5-8. Hybrid retrieval, cross-reference expansion, status filter, rerank and relevance gate
    retrieval = await retrieve_contexts(
        analysis=analysis,
        store=store,
        client=client,
        top_k=40,
        max_extra=8,
        rerank_top_n=8,
        query_vector=query_vector,
        use_vector=embedding_available,
        category=payload.category,
    )
    final_contexts = retrieval.contexts
    status_warnings = retrieval.status_warnings

    # 9. Generator
    generator = AnswerGenerator(client=client)

    if stream:
        # Return SSE streaming response
        return StreamingResponse(
            generator.generate_answer_stream(
                query=cleaned_query,
                contexts=final_contexts,
                language=target_language,
                mode=payload.mode,
                status_warnings=status_warnings,
            ),
            media_type="text/event-stream"
        )

    # Non-streaming generation + validation pass
    try:
        gen_result = await generator.generate_answer(
            query=cleaned_query,
            contexts=final_contexts,
            language=target_language,
            mode=payload.mode,
        )
    except RuntimeError as e:
        logger.error(f"Answer generation unavailable: {e}")
        raise HTTPException(
            status_code=503,
            detail="Javob yaratish xizmati vaqtincha mavjud emas. Iltimos, birozdan so'ng qayta urinib ko'ring.",
        )

    response_payload = QueryResponse(
        answer=gen_result.clean_answer or gen_result.answer,
        clean_answer=gen_result.clean_answer or gen_result.answer,
        telegram_formatted=gen_result.telegram_formatted or gen_result.answer,
        citations=gen_result.citations,
        detected_language=target_language,
        detected_script=analysis.detected_script,
        mode=payload.mode,
        is_refusal=gen_result.is_refusal,
        validation_passed=gen_result.validation_passed,
        status_warnings=status_warnings,
        conversation_id=payload.conversation_id,
        cached=False,
        retrieval_confidence=round(retrieval.decision.confidence, 3) if retrieval.decision else None,
    )

    # Cache only verified, substantive answers: an answer that failed citation validation (or a refusal)
    # must not be replayed for 24h as if it were authoritative.
    if (
        response_payload.validation_passed
        and not response_payload.is_refusal
        and len((response_payload.clean_answer or response_payload.answer).strip()) > 80
    ):
        cached_data = response_payload.model_dump()
        cached_data["_groups"] = groups_key
        cached_data["_filtered"] = has_filters
        cache.set(cache_text, target_language, payload.mode, cached_data, vector=query_vector)


    return response_payload
