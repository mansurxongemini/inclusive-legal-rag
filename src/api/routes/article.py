from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from src.schema.canonical import CanonicalArticle

router = APIRouter(prefix="/api/v1", tags=["Articles"])


@router.get("/article/{canonical_id}", response_model=CanonicalArticle)
async def get_article_by_id(canonical_id: str):
    """
    Fetch one canonical entity directly (all three languages, full metadata, points).
    Used for 'show me the full text of the article you cited.'
    """
    from src.api.app import get_store
    store = get_store()
    article = store.get_article(canonical_id)
    if not article:
        raise HTTPException(
            status_code=404,
            detail=f"Kanonik modda topilmadi (Article not found): {canonical_id}"
        )
    return article


@router.get("/articles", response_model=List[CanonicalArticle])
async def list_articles(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    from src.api.app import get_store
    store = get_store()
    return store.list_articles(limit=limit, offset=offset)
