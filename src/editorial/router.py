"""Admin API: Tahririyat (curated answers, legal links, notifications)."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.auth.admin import require_admin
from src.editorial import service as svc
from src.editorial.schemas import CuratedAnswerCreate, CuratedAnswerUpdate, LegalLinkCreate, NotificationResolve
from src.editorial.store import EditorialStore
from src.editorial.watch import check_legal_links

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/editorial", tags=["Editorial"])
_ADMIN = [Depends(require_admin)]


def _get_editorial() -> EditorialStore:
    return EditorialStore()


def _get_store():
    from src.api.app import get_store
    return get_store()


def _answer_detail(editorial: EditorialStore, answer: dict) -> dict:
    links = editorial.list_links(owner_type="curated", owner_id=str(answer["id"]))
    return {**answer, "links": links, "links_count": len(links)}


class AltQuestionsFix(BaseModel):
    alt_questions: List[str] = Field(default_factory=list, max_length=20)


# -- answers -------------------------------------------------------------------------------------
@router.get("/answers", dependencies=_ADMIN)
async def list_answers(
    status: str = Query(default="all"),
    q: Optional[str] = Query(default=None, max_length=500),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    editorial = _get_editorial()
    items, total = editorial.list_answers(status=status, q=q, limit=limit, offset=offset)
    out = []
    for a in items:
        links = editorial.list_links(owner_type="curated", owner_id=str(a["id"]))
        out.append({**a, "links_count": len(links)})
    return {"total": total, "items": out}


@router.post("/answers", dependencies=_ADMIN)
async def create_answer(payload: CuratedAnswerCreate):
    editorial = _get_editorial()
    alts = [str(x).strip()[:500] for x in (payload.alt_questions or []) if str(x).strip()][:20]
    answer = editorial.create_answer(
        question=payload.question.strip(),
        alt_questions=alts,
        answer_md=payload.answer_md.strip(),
        language=payload.language.strip() or "uz",
        category=payload.category.strip() or "general",
        author=payload.author.strip(),
    )
    return _answer_detail(editorial, answer)


@router.get("/answers/{answer_id}", dependencies=_ADMIN)
async def get_answer(answer_id: int):
    editorial = _get_editorial()
    answer = editorial.get_answer(answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="Javob topilmadi.")
    history = editorial.get_history(answer_id)
    return {**_answer_detail(editorial, answer), "history": history}


@router.put("/answers/{answer_id}", dependencies=_ADMIN)
async def update_answer(answer_id: int, payload: CuratedAnswerUpdate):
    editorial = _get_editorial()
    answer = editorial.get_answer(answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="Javob topilmadi.")
    fields: dict = {}
    if payload.question is not None:
        fields["question"] = payload.question.strip()
    if payload.alt_questions is not None:
        fields["alt_questions"] = [str(x).strip()[:500] for x in payload.alt_questions if str(x).strip()][:20]
    if payload.answer_md is not None:
        fields["answer_md"] = payload.answer_md.strip()
    if payload.language is not None:
        fields["language"] = payload.language.strip() or "uz"
    if payload.category is not None:
        fields["category"] = payload.category.strip() or "general"
    updated = editorial.update_answer(answer_id, fields, editor="", action="edit")
    # Content edit on a published answer keeps it published only if links still valid; otherwise re-project.
    if updated and updated["status"] == "published":
        store = _get_store()
        try:
            await svc.project_answer(store, editorial, updated)
            svc._invalidate_cache()
        except Exception as e:
            logger.error(f"Re-projection after edit failed: {e}")
    return _answer_detail(editorial, updated or answer)


@router.delete("/answers/{answer_id}", dependencies=_ADMIN)
async def delete_answer(answer_id: int):
    editorial = _get_editorial()
    answer = editorial.get_answer(answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="Javob topilmadi.")
    store = _get_store()
    svc.unproject_answer(store, answer_id)
    editorial.delete_answer(answer_id)
    return {"status": "success", "message": "Javob o'chirildi."}


@router.post("/answers/{answer_id}/publish", dependencies=_ADMIN)
async def publish_answer(answer_id: int):
    editorial = _get_editorial()
    if not editorial.get_answer(answer_id):
        raise HTTPException(status_code=404, detail="Javob topilmadi.")
    store = _get_store()
    try:
        updated = await svc.publish_answer(store, editorial, answer_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Javob topilmadi.")
    except ValueError as e:
        msg = str(e)
        if msg == "legal_basis_required":
            raise HTTPException(status_code=409, detail="Nashr uchun kamida 1 ta huquqiy asos (Lex.uz moddasi) majburiy.")
        if msg == "open_notifications":
            raise HTTPException(status_code=409, detail="Bu javob bo'yicha hal qilinmagan bildirishnomalar bor. "
                                                        "Avval ularni \"Bildirishnomalar\" bo'limida ko'rib chiqing.")
        if msg.startswith("link_stale:"):
            cid = msg.split(":", 1)[1]
            raise HTTPException(status_code=409, detail=f"{cid} moddasi javob yozilganidan keyin o'zgargan. "
                                                        "Yangi matnni o'qib, moddani qayta bog'lang.")
        raise HTTPException(status_code=409, detail=f"Huquqiy asos yaroqsiz: {msg}.")
    return _answer_detail(editorial, updated)


@router.post("/answers/{answer_id}/unpublish", dependencies=_ADMIN)
async def unpublish_answer(answer_id: int):
    editorial = _get_editorial()
    answer = editorial.get_answer(answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="Javob topilmadi.")
    updated = editorial.update_answer(answer_id, {"status": "archived"}, editor="", action="unpublish")
    store = _get_store()
    svc.unproject_answer(store, answer_id)
    return _answer_detail(editorial, updated or answer)


# -- links ----------------------------------------------------------------------------------------
@router.post("/answers/{answer_id}/links", dependencies=_ADMIN)
async def add_link(answer_id: int, payload: LegalLinkCreate):
    editorial = _get_editorial()
    answer = editorial.get_answer(answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="Javob topilmadi.")
    store = _get_store()
    article, err = svc.validate_link_target(store, payload.canonical_id.strip())
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Bunday modda store'da topilmadi.")
    if err == "not_lex":
        raise HTTPException(status_code=422, detail="Faqat Lex.uz (source_type=lex) moddalarini bog'lash mumkin.")
    if err == "not_active":
        raise HTTPException(status_code=422, detail="Faqat ACTIVE statusdagi moddani bog'lash mumkin.")
    assert article is not None
    text, h, st = svc.snapshot_of(article)
    link = editorial.add_link(
        owner_type="curated", owner_id=str(answer_id),
        canonical_id=article.canonical_id,
        law_id=article.metadata.law_id,
        article_label=f"{article.metadata.law_number} {article.metadata.article_number}",
        snapshot_text=text, snapshot_hash=h, snapshot_status=st,
        note=payload.note.strip()[:1000],
    )
    # A new basis on a published answer refreshes its projection immediately.
    if answer["status"] == "published":
        try:
            await svc.project_answer(store, editorial, editorial.get_answer(answer_id))
            svc._invalidate_cache()
        except Exception as e:
            logger.error(f"Re-projection after link add failed: {e}")
    return link


@router.delete("/answers/{answer_id}/links/{canonical_id}", dependencies=_ADMIN)
async def remove_link(answer_id: int, canonical_id: str):
    editorial = _get_editorial()
    if not editorial.get_answer(answer_id):
        raise HTTPException(status_code=404, detail="Javob topilmadi.")
    ok = editorial.remove_link(owner_type="curated", owner_id=str(answer_id), canonical_id=canonical_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Bog'lanish topilmadi.")
    answer = editorial.get_answer(answer_id)
    if answer and answer["status"] == "published":
        store = _get_store()
        remaining = editorial.list_links(owner_type="curated", owner_id=str(answer_id))
        if not remaining:
            # Last basis removed: a published answer without basis is suspended, not silently kept.
            editorial.update_answer(answer_id, {"status": "needs_review"}, editor="", action="basis_removed")
            svc.unproject_answer(store, answer_id)
        else:
            try:
                await svc.project_answer(store, editorial, answer)
                svc._invalidate_cache()
            except Exception as e:
                logger.error(f"Re-projection after link remove failed: {e}")
    return {"status": "success"}


# -- norms & laws (modda tanlash) ------------------------------------------------------------------
@router.get("/norms/search", dependencies=_ADMIN)
async def search_norms(
    q: str = Query(default="", max_length=500),
    law_id: Optional[str] = Query(default=None, max_length=256),
    limit: int = Query(default=20, ge=1, le=100),
):
    store = _get_store()
    if not q.strip():
        # Law-scoped browsing without a query term.
        if law_id:
            arts = store.get_articles_by_law(law_id)[:limit]
            return {"items": [
                {
                    "canonical_id": a["canonical_id"],
                    "law_title": a.get("law_title", ""),
                    "law_number": a.get("law_number", ""),
                    "article_number": a.get("article_number", ""),
                    "preview": (a.get("preview") or "")[:300],
                    "source_url": a.get("source_url", ""),
                    "status": a.get("status", "active"),
                } for a in arts
            ]}
        return {"items": []}
    hits = store.fts_store.bm25_search(q.strip(), top_k=limit * 2)
    cids = [h["canonical_id"] for h in hits]
    arts = store.get_articles_batch(cids)
    items = []
    for cid in cids:
        art = arts.get(cid)
        if art is None:
            continue
        if getattr(art.metadata, "source_type", "lex") != "lex":
            continue
        if law_id and art.metadata.law_id != law_id:
            continue
        items.append({
            "canonical_id": art.canonical_id,
            "law_title": art.get_law_title("uz"),
            "law_number": art.metadata.law_number,
            "article_number": art.metadata.article_number,
            "preview": art.get_text("uz")[:300],
            "source_url": art.metadata.source_url,
            "status": art.metadata.status.value,
        })
        if len(items) >= limit:
            break
    return {"items": items}


@router.get("/laws", dependencies=_ADMIN)
async def list_laws():
    store = _get_store()
    docs = store.list_documents()
    return {"items": [
        {
            "law_id": d.get("law_id", ""),
            "law_title": d.get("law_title", ""),
            "law_number": d.get("law_number", ""),
            "norm_count": d.get("norm_count", 0),
        } for d in docs
        if d.get("law_id") != svc.CURATED_LAW_ID and not str(d.get("law_id", "")).startswith("huquqplus")
    ]}


# -- notifications ----------------------------------------------------------------------------------
@router.get("/notifications", dependencies=_ADMIN)
async def list_notifications(
    status: str = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    editorial = _get_editorial()
    items, total = editorial.list_notifications(status=status, limit=limit, offset=offset)
    # Attach question or huquqplus article metadata for display
    enriched = []
    for n in items:
        question = ""
        post_title = ""
        post_url = ""
        wp_admin_url = ""
        if n["owner_type"] == "curated":
            try:
                a = editorial.get_answer(int(n["owner_id"]))
                question = (a or {}).get("question", "")
            except ValueError:
                pass
        elif n["owner_type"] == "huquqplus":
            parts = n["owner_id"].split(":", 1)
            if len(parts) == 2:
                lang, wp_id_str = parts
                try:
                    wp_id = int(wp_id_str)
                    wp_admin_url = f"https://huquqplus.uz/wp-admin/post.php?post={wp_id}&action=edit"
                    from src.integrations.huquqplus_sync import get_huquqplus_db_path
                    from src.storage.sqlite_utils import connect as _sqlite_conn
                    with _sqlite_conn(get_huquqplus_db_path(), timeout=10.0) as conn:
                        row = conn.execute(
                            "SELECT title, url FROM hp_posts WHERE wp_id = ? AND lang = ?",
                            (wp_id, lang)
                        ).fetchone()
                        if row:
                            post_title = row[0]
                            post_url = row[1]
                except Exception as e:
                    logger.warning(f"Huquq+ post metadata error for {n['owner_id']}: {e}")
        enriched.append({
            **n,
            "question": question or post_title,
            "title": post_title,
            "url": post_url,
            "wp_admin_url": wp_admin_url,
        })
    return {"total": total, "items": enriched, "open_count": editorial.count_open_notifications()}


@router.get("/notifications/count", dependencies=_ADMIN)
async def notifications_count():
    return {"open": _get_editorial().count_open_notifications()}


@router.post("/notifications/{notif_id}/resolve", dependencies=_ADMIN)
async def resolve_notification(notif_id: int, payload: NotificationResolve):
    editorial = _get_editorial()
    notif = editorial.get_notification(notif_id)
    if not notif:
        raise HTTPException(status_code=404, detail="Bildirishnoma topilmadi.")
    if notif["status"] != "open":
        raise HTTPException(status_code=409, detail="Bildirishnoma allaqachon hal qilingan.")
    if payload.action not in ("keep", "edited", "unpublish", "delete"):
        raise HTTPException(status_code=422, detail="Noto'g'ri harakat.")
    if notif.get("owner_type") == "huquqplus" and payload.action == "delete":
        raise HTTPException(status_code=422, detail="Huquq+ maqolasini o'chirish mumkin emas.")
    store = _get_store()
    try:
        result = await svc.resolve_notification(
            store, editorial, notif, action=payload.action, note=payload.note.strip(), resolved_by="")
    except KeyError:
        raise HTTPException(status_code=404, detail="Bog'langan javob topilmadi.")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return result


@router.post("/check-links", dependencies=_ADMIN)
async def run_check_links():
    store = _get_store()
    result = check_legal_links(store, _get_editorial())
    return result
