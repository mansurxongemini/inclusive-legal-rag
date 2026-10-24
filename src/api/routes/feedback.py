from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from src.api.auth.admin import require_admin
from src.api.middleware.rate_limiter import rate_limiter
from src.config import settings

router = APIRouter(prefix="/api/v1", tags=["Feedback"])


class FeedbackRequest(BaseModel):
    query: str = Field(..., max_length=4000, description="The user query")
    answer: str = Field(..., max_length=20000, description="The generated answer")
    canonical_ids: List[str] = Field(default_factory=list, max_length=50, description="Citations attached to answer")
    rating: int = Field(default=3, ge=1, le=5, description="1 to 5 satisfaction rating")
    feedback_text: Optional[str] = Field(default="", max_length=4000, description="Reviewer or citizen comment")


# Plain `def` handlers run in FastAPI's thread pool: the SQLite writes do not stall the event loop.

@router.post("/feedback")
def submit_feedback(request: Request, payload: FeedbackRequest):
    """
    Submits user or legal reviewer feedback on an answer, feeding the review queue and eval set. Open to the public (the
    site's feedback buttons), so each address may send only FEEDBACK_RATE_PER_MINUTE of them a minute.
    """
    rate_limiter.check(request, scope="feedback", limit=settings.FEEDBACK_RATE_PER_MINUTE)
    from src.api.app import get_store
    store = get_store()
    store.fts_store.record_feedback(
        query=payload.query,
        answer=payload.answer,
        canonical_ids=payload.canonical_ids,
        rating=payload.rating,
        feedback_text=payload.feedback_text or "",
    )
    return {"status": "success", "message": "Fikr-mulohazangiz qabul qilindi. Rahmat!"}


@router.get("/feedback", dependencies=[Depends(require_admin)])
def get_feedback_records(limit: int = Query(default=50, ge=1, le=500)):
    """Lists stored citizen questions and answers - administrators only (contains personal data)."""
    from src.api.app import get_store
    store = get_store()
    return store.fts_store.get_feedback_records(limit=limit)
