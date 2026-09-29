import json
import logging
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.nlp.query_analyzer import QueryAnalyzer, SupportedLanguage
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.expansion import expand_cross_references
from src.retrieval.status_filter import apply_status_and_amendment_filter
from src.retrieval.reranker import Reranker
from src.generation.generator import AnswerGenerator
from src.generation.validator import CitationItem
from src.api.middleware.security import sanitize_user_input
from src.api.middleware.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Query"])


class QueryRequest(BaseModel):
    question: str = Field(..., description="Legal question from citizen or reviewer")
    language: Literal["auto", "uz", "ru", "en"] = Field(default="auto", description="Preferred response language")
    mode: Literal["plain", "legal_text", "subsumption"] = Field(default="plain", description="plain language summary, verbatim legal text, or German-style legal subsumption analysis")
    conversation_id: Optional[str] = Field(default=None, description="Optional conversation trace ID")


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

    from src.api.app import get_store, get_cache, get_client
    store = get_store()
    cache = get_cache()
    client = get_client()

    # 3. Query analysis: detect language and script, normalize Cyrillic -> Latin if Uzbek
    user_lang = None if payload.language == "auto" else payload.language
    analysis = QueryAnalyzer.analyze(cleaned_query, user_language=user_lang)
    target_language = analysis.detected_language

    # 4. Check Layer 1: Canonical Normalized Query Cache (0.1ms)
    if not stream:
        cached_resp = cache.get(cleaned_query, target_language, payload.mode)
        if cached_resp:
            cached_resp["cached"] = True
            return cached_resp

    # Compute dense query vector for semantic cache check and retrieval
    query_vector = None
    if not client.is_mock:
        try:
            q_vectors = await client.get_embeddings([analysis.normalized_query])
            if q_vectors:
                query_vector = q_vectors[0]
                # Check Layer 2: Semantic Vector Cache (similarity >= 96%)
                if not stream:
                    sem_cached = cache.get_semantic(query_vector, target_language, payload.mode, threshold=0.96)
                    if sem_cached:
                        sem_cached["cached"] = True
                        return sem_cached
        except Exception as e:
            logger.warning(f"Error computing query vector for semantic cache: {e}")

    # 5. Hybrid retrieval (BM25 + Vector + RRF) with comprehensive candidate pool
    retriever = HybridRetriever(store, client=client)
    raw_candidates = await retriever.retrieve(analysis, top_k=60)


    # 6. 1-hop cross-reference expansion
    expanded_candidates = expand_cross_references(raw_candidates, store, max_extra=6)

    # 7. Status & amendment filtering
    filtered_candidates, status_warnings = apply_status_and_amendment_filter(expanded_candidates, store)

    # 8. Rerank to top-8
    reranker = Reranker(client=client)
    final_contexts = await reranker.rerank(
        query=analysis.normalized_query,
        language=target_language,
        candidates=filtered_candidates,
        store=store,
        top_n=8,
    )

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
            ),
            media_type="text/event-stream"
        )

    # Non-streaming generation + validation pass
    gen_result = await generator.generate_answer(
        query=cleaned_query,
        contexts=final_contexts,
        language=target_language,
        mode=payload.mode,
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
    )

    # Store in query cache with dense vector for future semantic matching
    cache.set(
        cleaned_query,
        target_language,
        payload.mode,
        response_payload.model_dump(),
        vector=query_vector
    )


    return response_payload
