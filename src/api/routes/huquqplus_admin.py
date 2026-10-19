"""
Admin API for Huquq+ sync operations: status, posts list, trigger full sync, resync specific post.
All endpoints require admin authentication (require_admin).
"""
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from src.api.auth.admin import require_admin
from src.integrations.huquqplus_sync import (
    full_sync,
    get_sync_status,
    list_synced_posts,
    resync_post,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/huquqplus", tags=["HuquqPlus Admin"])
_ADMIN = [Depends(require_admin)]


@router.get("/status", dependencies=_ADMIN)
async def admin_huquqplus_status():
    """
    Sinxronlash holati: postlar soni til/section/status bo'yicha, oxirgi sync_runs,
    navbat statistikasi, resolve bo'lmagan havolalar soni.
    """
    return get_sync_status()


def _get_law_source_url(store, law_id: str) -> str:
    if store is None or not hasattr(store, "fts_store") or store.fts_store is None:
        return ""
    try:
        with store.fts_store._get_connection() as conn:
            row = conn.execute("""
                SELECT json_extract(json_data, '$.metadata.source_url')
                FROM articles_metadata
                WHERE json_extract(json_data, '$.metadata.law_id') = ?
                  AND json_extract(json_data, '$.metadata.source_url') IS NOT NULL
                LIMIT 1
            """, (law_id,)).fetchone()
        if not row or not row[0]:
            return ""
        return str(row[0]).split("#")[0]
    except Exception as e:
        logger.warning(f"Error extracting source_url for {law_id}: {e}")
        return ""


def _enrich_posts_with_law_details(posts: list, store=None) -> None:
    if store is None:
        try:
            from src.api.app import get_store
            store = get_store()
        except Exception:
            store = None

    from src.editorial.doc_watch import law_label

    label_cache = {}
    url_cache = {}

    for post in posts:
        unresolved = post.get("unresolved_links") or []
        for ref in unresolved:
            law_id = ref.get("law_id")
            if law_id:
                if law_id not in label_cache:
                    label_cache[law_id] = law_label(store, law_id)
                if law_id not in url_cache:
                    url_cache[law_id] = _get_law_source_url(store, law_id)

                ref["law_label"] = label_cache[law_id]
                ref["source_url"] = url_cache[law_id] or ref.get("url") or ""


@router.get("/posts", dependencies=_ADMIN)
async def admin_huquqplus_posts(
    lang: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=500),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    Sinxronlangan Huquq+ maqolalari ro'yxati: sarlavha, url, modified, bo'laklar soni,
    resolve bo'lgan/bo'lmagan havolalar.
    """
    posts, total = list_synced_posts(lang=lang, status=status, q=q, limit=limit, offset=offset)
    _enrich_posts_with_law_details(posts)
    return {"total": total, "items": posts}


@router.get("/posts/{lang}/{wp_id}", dependencies=_ADMIN)
async def admin_huquqplus_get_post(lang: str, wp_id: int):
    """
    Alohida maqola tafsilotlari (bog'langan aktlar bilan).
    """
    if lang not in ("uz", "ru"):
        raise HTTPException(status_code=422, detail="Til 'uz' yoki 'ru' bo'lishi kerak.")
    posts, _ = list_synced_posts(lang=lang, limit=1000, offset=0, q=None)
    matched = next((p for p in posts if p.get("wp_id") == wp_id and p.get("lang") == lang), None)
    if not matched:
        raise HTTPException(status_code=404, detail="Maqola topilmadi.")
    _enrich_posts_with_law_details([matched])
    return matched


@router.post("/sync", status_code=202, dependencies=_ADMIN)
async def admin_huquqplus_trigger_sync(background_tasks: BackgroundTasks):
    """
    To'liq sinxronlashni fonda boshlaydi (202 Accepted).
    """
    background_tasks.add_task(full_sync)
    return {"status": "accepted", "message": "To'liq sinxronlash fonda boshlandi."}


@router.post("/posts/{lang}/{wp_id}/resync", dependencies=_ADMIN)
async def admin_huquqplus_resync_post(lang: str, wp_id: int):
    """
    Alohida maqolani darhol qayta sinxronlaydi.
    """
    if lang not in ("uz", "ru"):
        raise HTTPException(status_code=422, detail="Til 'uz' yoki 'ru' bo'lishi kerak.")
    try:
        res = await resync_post(wp_id, lang)
        return res
    except Exception as exc:
        logger.error(f"Postni qayta sinxronlashda xatolik ({wp_id}, {lang}): {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
