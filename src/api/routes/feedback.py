from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["Feedback"])


class FeedbackRequest(BaseModel):
    query: str = Field(..., description="The user query")
    answer: str = Field(..., description="The generated answer")
    canonical_ids: List[str] = Field(default_factory=list, description="Citations attached to answer")
    rating: int = Field(default=3, ge=1, le=5, description="1 to 5 satisfaction rating")
    feedback_text: Optional[str] = Field(default="", description="Reviewer or citizen comment")


@router.post("/feedback")
async def submit_feedback(payload: FeedbackRequest):
    """
    Submits user or legal reviewer feedback on an answer, feeding the review queue and eval set.
    """
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


@router.get("/feedback")
async def get_feedback_records(limit: int = 50):
    from src.api.app import get_store
    store = get_store()
    return store.fts_store.get_feedback_records(limit=limit)
