import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from src.api.auth.admin import require_admin
from src.schema.canonical import ArticleStatus
from src.storage.sqlite_utils import connect as sqlite_connect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin"])

# Static HTML pages stay public; every /api/v1/admin/* route requires administrator access.
_ADMIN = [Depends(require_admin)]



def _invalidate_answer_cache() -> None:
    """Cached answers describe the corpus as it was; drop them whenever norms change."""
    from src.api.app import get_cache
    try:
        get_cache().clear()
    except Exception as e:
        logger.warning(f"Could not clear query cache: {e}")


_STATIC = Path(__file__).resolve().parent.parent.parent / "admin" / "static"


def _read_static(name: str, missing: str) -> str:
    f = _STATIC / name
    return f.read_text(encoding="utf-8") if f.exists() else missing


@router.get("/", response_class=HTMLResponse)
@router.get("/ask", response_class=HTMLResponse)
async def serve_public_page():
    """Citizen-facing, accessible question page."""
    return _read_static("ask.html", "<h1>ask.html not found.</h1>")


@router.get("/admin", response_class=HTMLResponse)
async def serve_admin_dashboard():
    return _read_static("index.html", "<h1>Admin dashboard index.html not found.</h1>")


@router.get("/admin-v2")
async def serve_admin_dashboard_v2():
    return RedirectResponse("/admin", status_code=307)


@router.get("/api/v1/admin/stats", dependencies=_ADMIN)
async def get_admin_stats():
    from src.api.app import get_store
    from src.api.routes.health import get_process_memory_mb
    from src.integrations.huquqplus_sync import get_sync_status
    from src.gateway.clients import get_client_store
    from src.editorial.store import EditorialStore
    store = get_store()

    # 1. Lex.uz aktlari va bandlari (faqat lex manbasi)
    with sqlite_connect(store.fts_store.db_path) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT 
                COUNT(*) as total_articles,
                COUNT(DISTINCT json_extract(json_data, '$.metadata.law_id')) as total_laws
            FROM articles_metadata
            WHERE (json_extract(json_data, '$.metadata.source_type') = 'lex' OR json_extract(json_data, '$.metadata.source_type') IS NULL)
              AND canonical_id NOT LIKE 'hp_%' AND canonical_id NOT LIKE 'qa_%'
        """)
        row = c.fetchone()
        lex_articles = row[0] if row else 0
        lex_laws = row[1] if row else 0

        c.execute("""
            SELECT category, COUNT(*) 
            FROM articles_metadata 
            WHERE (json_extract(json_data, '$.metadata.source_type') = 'lex' OR json_extract(json_data, '$.metadata.source_type') IS NULL)
              AND canonical_id NOT LIKE 'hp_%' AND canonical_id NOT LIKE 'qa_%'
            GROUP BY category
        """)
        categories = dict(c.fetchall())

        c.execute("""
            SELECT status, COUNT(*) 
            FROM articles_metadata 
            WHERE (json_extract(json_data, '$.metadata.source_type') = 'lex' OR json_extract(json_data, '$.metadata.source_type') IS NULL)
              AND canonical_id NOT LIKE 'hp_%' AND canonical_id NOT LIKE 'qa_%'
            GROUP BY status
        """)
        statuses = dict(c.fetchall())

    # 2. Huquq+ maqolalari (uz va ru)
    hp_active_uz = 0
    hp_active_ru = 0
    hp_total_active = 0
    try:
        hp_status = get_sync_status()
        hp_total_active = hp_status.get("total_active_posts", 0)
        for p in hp_status.get("posts_summary", []):
            if p.get("status") == "active":
                cnt = p.get("cnt", 0)
                if p.get("lang") == "uz":
                    hp_active_uz += cnt
                elif p.get("lang") == "ru":
                    hp_active_ru += cnt
    except Exception as e:
        logger.warning(f"Could not load Huquq+ status for stats: {e}")

    # 3. Tahririyat: nashrdagi savol-javoblar va ochiq bildirishnomalar
    published_qa = 0
    open_notifications = 0
    try:
        ed_store = EditorialStore(str(Path(store.fts_store.db_path).parent / "editorial.db"))
        with sqlite_connect(ed_store.db_path) as ed_conn:
            ec = ed_conn.cursor()
            ec.execute("SELECT COUNT(*) FROM curated_answers WHERE status = 'published'")
            published_qa = ec.fetchone()[0]
            ec.execute("SELECT COUNT(*) FROM notifications WHERE status = 'open'")
            open_notifications = ec.fetchone()[0]
    except Exception as e:
        logger.warning(f"Could not load editorial counts for stats: {e}")

    # 4. API mijozlari va so'rovlar soni
    active_clients = 0
    total_requests_served = 0
    try:
        gw_store = get_client_store()
        clients = gw_store.list_clients()
        active_clients = sum(1 for cl in clients if cl.is_active)
        # requests counted per client and day; kept for the last 30 days
        total_requests_served = sum(int(day.get("requests") or 0) for cl in clients for day in gw_store.usage(cl.client_id))
    except Exception as e:
        logger.warning(f"Could not load gateway clients for stats: {e}")

    return {
        "total_articles": lex_articles,
        "total_documents": lex_laws,
        "lex_articles_count": lex_articles,
        "lex_documents_count": lex_laws,
        "huquqplus_active_posts": hp_total_active,
        "huquqplus_uz_count": hp_active_uz,
        "huquqplus_ru_count": hp_active_ru,
        "published_qa_count": published_qa,
        "open_notifications_count": open_notifications,
        "active_api_clients": active_clients,
        "total_requests_served": total_requests_served,
        "system_status": "healthy",
        "rss_memory_mb": get_process_memory_mb(),
        "categories": categories,
        "statuses": statuses,
    }


@router.get("/api/v1/admin/hierarchy", dependencies=_ADMIN)
async def get_admin_hierarchy():
    """Returns all legislation grouped hierarchically into Codes, Laws, Conventions, and Others."""
    from src.api.app import get_store
    store = get_store()

    with sqlite_connect(store.fts_store.db_path) as conn:
        c = conn.cursor()
        c.execute("""
        SELECT 
            json_extract(json_data, '$.metadata.law_id') as law_id,
            json_extract(json_data, '$.metadata.law_title.uz') as title_uz,
            json_extract(json_data, '$.metadata.law_title.ru') as title_ru,
            json_extract(json_data, '$.metadata.law_number') as law_num,
            json_extract(json_data, '$.metadata.category') as category,
            status,
            COUNT(*) as art_count,
            SUM(CASE WHEN length(json_extract(json_data, '$.translations.ru')) > 0 THEN 1 ELSE 0 END) as ru_art_count
        FROM articles_metadata
        GROUP BY law_id
        ORDER BY art_count DESC
    """)
        rows = c.fetchall()

    types = {
        "constitution": {
            "id": "constitution",
            "title": "Konstitutsiya (Constitution)",
            "description": "O'zbekiston Respublikasi Konstitutsiyasi (Oliy yuridik kuchga ega Bosh qonun)",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "codes": {
            "id": "codes",
            "title": "Kodekslar (Codes)",
            "description": "O'zbekiston Respublikasining barcha amaldagi 19 ta kodeksi",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "laws": {
            "id": "laws",
            "title": "Qonunlar (Laws - O'RQ)",
            "description": "O'zbekiston Respublikasining barcha amaldagi qonunlari",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "decrees": {
            "id": "decrees",
            "title": "Prezident Farmonlari (PF)",
            "description": "O'zbekiston Respublikasi Prezidentining amaldagi farmonlari",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "resolutions": {
            "id": "resolutions",
            "title": "Prezident va Hukumat Qarorlari (PQ, VMQ)",
            "description": "Vazirlar Mahkamasi va Prezidentning sohalar bo'yicha amaldagi qarorlari",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "regulations": {
            "id": "regulations",
            "title": "Hukumat va Davlat Nizomlari",
            "description": "Hukumat va idoraviy tasdiqlangan qoidalar, reglamentlar va nizomlar",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "orders": {
            "id": "orders",
            "title": "Vazirlik va Idoralar Buyruqlari",
            "description": "Adliya vazirligidan ro'yxatdan o'tgan vazirlik va idoraviy normativ buyruqlar",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "parliament": {
            "id": "parliament",
            "title": "Oliy Majlis Qarorlari",
            "description": "Oliy Majlis Qonunchilik palatasi va Senatining normativ qarorlari",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "directives": {
            "id": "directives",
            "title": "Farmoyishlar",
            "description": "Prezident va Hukumatning normativ xarakterdagi amaldagi farmoyishlari",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "conventions": {
            "id": "conventions",
            "title": "Xalqaro Shartnomalar va Konvensiyalar",
            "description": "O'zbekiston ratifikatsiya qilgan xalqaro shartnomalar, bitimlar va konvensiyalar",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "commentary": {
            "id": "commentary",
            "title": "Huquqiy Sharhlar va Maqolalar",
            "description": "Norma.uz, Advice.uz, Adliya vazirligi va yetakchi huquqiy portallarning tushuntirish maqolalari",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
    }

    CODE_SLUGS = {
        "mehnat_code", "oila_code", "uy_joy_code", "shaharsozlik_code",
        "yer_code", "saylov_code", "byudjet_code", "havo_code",
        "fuqarolik_code_1", "fuqarolik_code_2", "mjtk_code", "jinoyat_code",
        "soliq_code", "bojxona_code", "jik_code", "fpk_code",
        "ipk_code", "msiytk_code", "jpk_code"
    }

    total_ru_count = 0
    for law_id, title_uz, title_ru, law_num, cat, status, art_count, ru_count in rows:
        ru_val = ru_count or 0
        total_ru_count += ru_val
        doc_info = {
            "law_id": law_id,
            "title_uz": title_uz or law_id,
            "title_ru": title_ru or title_uz or law_id,
            "law_number": law_num or "",
            "category": cat,
            "status": status,
            "article_count": art_count,
            "ru_article_count": ru_val,
        }

        lid = str(law_id).lower()
        title_lower = str(title_uz).lower()
        cat_lower = str(cat or "").lower()
        num_lower = str(law_num or "").lower()

        if "constitution" in lid or "konstitutsiy" in lid or cat_lower == "constitution":
            target = "constitution"
        elif lid in CODE_SLUGS or cat_lower in ["codes", "code"]:
            target = "codes"
        elif (
            lid.startswith("farmon_")
            or cat_lower == "decrees"
            or "пф-" in num_lower
            or "pf-" in num_lower
            or "farmon" in title_lower
            or "фармон" in title_lower
        ):
            target = "decrees"
        elif (
            lid.startswith("buyruq_")
            or cat_lower in ["departmental", "orders"]
            or "buyruq" in title_lower
            or "буйруқ" in title_lower
        ):
            target = "orders"
        elif (
            lid.startswith("om_qaror_")
            or cat_lower == "parliament_resolutions"
            or "oliy majlis" in title_lower
            or "кқ-" in num_lower
        ):
            target = "parliament"
        elif (
            lid.startswith("farmoyish_")
            or cat_lower == "directives"
            or "farmoyish" in title_lower
            or "фармойиш" in title_lower
            or "ф-" in num_lower
        ):
            target = "directives"
        elif (
            lid.startswith("xalqaro_")
            or lid.startswith("un_")
            or "crpd" in lid
            or cat_lower == "international_treaties"
            or "konvensiy" in title_lower
            or "битим" in title_lower
            or "shartnoma" in title_lower
        ):
            target = "conventions"
        elif (
            lid.startswith("web_")
            or lid.startswith("commentary_")
            or cat_lower in ["commentary", "legal_commentary"]
            or "advice.uz" in num_lower
            or "norma.uz" in num_lower
        ):
            target = "commentary"
        elif (
            lid.startswith("nizom_")
            or cat_lower == "regulations"
            or "nizom" in title_lower
            or "низом" in title_lower
        ):
            target = "regulations"
        elif (
            lid.startswith("qaror_")
            or lid.startswith("vmq_")
            or lid.startswith("pq_")
            or cat_lower == "resolutions"
            or "қарор" in title_lower
            or "qaror" in title_lower
            or "vmq" in num_lower
            or "пқ" in num_lower
            or "pq" in num_lower
        ):
            target = "resolutions"
        elif (
            lid.startswith("law_")
            or "o‘rq" in title_lower
            or "ўрқ" in title_lower
            or "qonun" in title_lower
            or cat_lower == "general_legislation"
        ):
            target = "laws"
        else:
            target = "resolutions"

        types[target]["documents"].append(doc_info)
        types[target]["total_articles"] += art_count
        types[target]["total_ru_articles"] += ru_val

    return {
        "total_articles": store.count(),
        "total_documents": len(rows),
        "total_ru_articles": total_ru_count,
        "types": types,
    }


@router.get("/api/v1/admin/documents/{law_id}/articles", dependencies=_ADMIN)
async def get_document_articles(law_id: str):
    """Returns all articles belonging to a specific law_id."""
    from src.api.app import get_store
    store = get_store()

    with sqlite_connect(store.fts_store.db_path) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT canonical_id, json_data, status, category, last_verified_date
            FROM articles_metadata
            WHERE json_extract(json_data, '$.metadata.law_id') = ?
            ORDER BY canonical_id ASC
        """, (law_id,))
        rows = c.fetchall()

    results = []
    for cid, jdata, st, cat, lvd in rows:
        try:
            d = json.loads(jdata)
            meta = d.get("metadata", {})
            trans = d.get("translations", {})
            results.append({
                "canonical_id": cid,
                "article_number": meta.get("article_number", ""),
                "title_uz": meta.get("article_title", {}).get("uz", ""),
                "title_ru": meta.get("article_title", {}).get("ru", ""),
                "text_uz": trans.get("uz", ""),
                "text_ru": trans.get("ru", ""),
                "status": st,
                "category": cat,
                "vector_model": meta.get("embedding_model_version", "bge-m3-2025-11-18"),
                "has_vector": True,
                "last_verified_date": lvd,
            })
        except Exception:
            pass

    # Natural sequential sort: 1, 2, 3... 18, 18-1, 19... 180, 181, 181-1... 302
    def article_natural_sort_key(item):
        num_str = item.get("article_number", "")
        nums = [int(x) for x in re.findall(r"\d+", num_str)]
        if not nums:
            return (999999, 0)
        if len(nums) == 1:
            return (nums[0], 0)
        return (nums[0], nums[1])

    results.sort(key=article_natural_sort_key)

    base_nums = []
    sub_count = 0
    for r in results:
        nums = [int(x) for x in re.findall(r"\d+", r["article_number"])]
        if len(nums) == 1:
            base_nums.append(nums[0])
        elif len(nums) > 1:
            sub_count += 1

    return {
        "law_id": law_id,
        "count": len(results),
        "max_article_number": max(base_nums) if base_nums else len(results),
        "sub_articles_count": sub_count,
        "articles": results,
    }


class ArticleUpdatePayload(BaseModel):
    title_uz: str = Field(..., min_length=1, max_length=500)
    title_ru: Optional[str] = Field(default=None, max_length=500)
    text_uz: str = Field(..., min_length=1)
    text_ru: Optional[str] = None
    status: str = "active"
    revectorize: bool = True


@router.put("/api/v1/admin/article/{canonical_id}", dependencies=_ADMIN)
async def update_admin_article(canonical_id: str, payload: ArticleUpdatePayload):
    """Updates article title/content and re-indexes into SQLite FTS5 and LanceDB."""
    from src.api.app import get_store, get_client
    store = get_store()
    client = get_client()

    existing = store.get_article(canonical_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Article {canonical_id} not found")

    # An unknown status used to be ignored in the database but still written to the JSON backup below.
    try:
        new_status = ArticleStatus(payload.status)
    except ValueError:
        allowed = ", ".join(s.value for s in ArticleStatus)
        raise HTTPException(status_code=422, detail=f"Noto'g'ri status: {payload.status!r}. Ruxsat etilgan: {allowed}")

    # Edit a copy: the store returns its cached instance, and a failed save must not leak into it.
    article = existing.model_copy(deep=True)

    # Update article data
    article.metadata.article_title["uz"] = payload.title_uz
    if payload.title_ru:
        article.metadata.article_title["ru"] = payload.title_ru

    article.translations["uz"] = payload.text_uz
    if payload.text_ru:
        article.translations["ru"] = payload.text_ru

    article.metadata.status = new_status

    # Update hash and timestamp
    hasher = hashlib.sha256()
    hasher.update(payload.text_uz.encode("utf-8"))
    article.metadata.source_hash = f"sha256:{hasher.hexdigest()}"
    article.metadata.last_verified_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Save to storage
    if payload.revectorize:
        try:
            await store.index_article(article, client=client)
        except Exception as e:
            logger.error(f"Re-vectorization failed for {canonical_id}: {e}", exc_info=True)
            raise HTTPException(status_code=502, detail="Qayta vektorlash amalga oshmadi. Modda o'zgarmadi.")
    else:
        store.fts_store.upsert_article(article)
    _invalidate_answer_cache()

    # If cached file exists, update JSON backup as well
    law_id = article.metadata.law_id
    for candidate_path in [Path("data/laws_catalog") / f"{law_id}.json", Path("data/laws_catalog/laws") / f"{law_id}.json"]:
        if candidate_path.exists():
            try:
                with open(candidate_path, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                updated = False
                for item in cached_data:
                    if item.get("canonical_id") == canonical_id:
                        item["translations"]["uz"] = payload.text_uz
                        if payload.text_ru:
                            item["translations"]["ru"] = payload.text_ru
                        item["metadata"]["article_title"]["uz"] = payload.title_uz
                        if payload.title_ru:
                            item["metadata"]["article_title"]["ru"] = payload.title_ru
                        item["metadata"]["status"] = payload.status
                        updated = True
                        break
                if updated:
                    with open(candidate_path, "w", encoding="utf-8") as f:
                        json.dump(cached_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Could not update JSON backup {candidate_path}: {e}")

    return {
        "status": "success",
        "canonical_id": canonical_id,
        "revectorized": payload.revectorize,
        "message": "Modda muvaffaqiyatli saqlandi va qayta vektorlandi!" if payload.revectorize else "Modda saqlandi."
    }


@router.delete("/api/v1/admin/article/{canonical_id}", dependencies=_ADMIN)
async def delete_admin_article(canonical_id: str):
    from src.api.app import get_store
    store = get_store()
    existing = store.get_article(canonical_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Article not found")
    store.delete_article(canonical_id)
    _invalidate_answer_cache()
    return {"status": "success", "message": f"{canonical_id} o'chirildi."}
