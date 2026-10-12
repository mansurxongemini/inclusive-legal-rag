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
    return {"total": total, "items": posts}


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
