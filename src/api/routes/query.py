import logging
from typing import List, Literal, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.domain.disability_taxonomy import CATEGORY_IDS, DISABILITY_GROUPS

from src.generation.validator import CitationItem
from src.api.middleware.security import sanitize_user_input
from src.api.middleware.rate_limiter import rate_limiter
from src.gateway.service import answer_question, answer_question_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Query"])


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000, description="Legal question from citizen or reviewer")
    language: Literal["auto", "uz", "ru", "en"] = Field(default="auto", description="Language of the question and of the answer; auto detects it")
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
    warnings: List[str] = []
    degraded: bool = False


@router.post("/query", response_model=QueryResponse)
async def query_legal_rag(
    request: Request,
    payload: QueryRequest,
    stream: bool = Query(default=False, description="Stream response tokens via SSE"),
):
    # 1. Rate limiting check
    rate_limiter.check(request)

    if stream:
        # an empty question must still be a 422, not a broken event stream
        if not sanitize_user_input(payload.question):
            raise HTTPException(status_code=422, detail="Savol matni bo'sh bo'lishi mumkin emas.")
        # Return SSE streaming response
        return StreamingResponse(
            answer_question_stream(
                payload.question,
                language=payload.language,
                mode=payload.mode,
                disability_group=payload.disability_group,
                category=payload.category,
            ),
            media_type="text/event-stream",
        )

    result = await answer_question(
        payload.question,
        language=payload.language,
        mode=payload.mode,
        disability_group=payload.disability_group,
        category=payload.category,
    )

    return QueryResponse(
        **result.model_dump(),
        conversation_id=payload.conversation_id,
    )

