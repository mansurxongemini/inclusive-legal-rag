from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.auth.admin import require_admin
from src.api.middleware.rate_limiter import limit_public_browsing
from src.schema.canonical import CanonicalArticle

router = APIRouter(prefix="/api/v1", tags=["Articles"])


# Plain `def` handlers: FastAPI runs them in its thread pool, so the SQLite reads do not stall the event loop.

@router.get("/article/{canonical_id}", response_model=CanonicalArticle)
def get_article_by_id(request: Request, canonical_id: str):
    """
    Fetch one canonical entity directly (all three languages, full metadata, points).
    Used for 'show me the full text of the article you cited.'
    """
    limit_public_browsing(request)
    from src.api.app import get_store
    store = get_store()
    article = store.get_article(canonical_id)
    if not article:
        raise HTTPException(
            status_code=404,
            detail=f"Kanonik modda topilmadi (Article not found): {canonical_id}"
        )
    return article


@router.get("/articles", response_model=List[CanonicalArticle], dependencies=[Depends(require_admin)])
def list_articles(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Pages through the whole corpus (full texts): administrators only. A public bulk dump of the database is not
    what the read endpoints are for; one cited article is fetched with GET /article/{canonical_id}."""
    from src.api.app import get_store
    store = get_store()
    return store.list_articles(limit=limit, offset=offset)
