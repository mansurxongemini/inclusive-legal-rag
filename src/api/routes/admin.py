import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.api.auth.admin import require_admin
from src.ingestion.lex_parser import parse_law_text_file
from src.ingestion.url_safety import is_lex_uz_url
from src.schema.canonical import CanonicalArticle, ArticleStatus
from src.storage.sqlite_utils import connect as sqlite_connect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin"])

# Static HTML pages stay public; every /api/v1/admin/* route requires administrator access.
_ADMIN = [Depends(require_admin)]

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


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


@router.get("/admin-v2", response_class=HTMLResponse)
async def serve_admin_dashboard_v2():
    static_file = Path(__file__).resolve().parent.parent.parent / "admin" / "static" / "index_v2.html"
    if static_file.exists():
        with open(static_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Admin dashboard index_v2.html not found.</h1>"


@router.get("/api/v1/admin/stats", dependencies=_ADMIN)
async def get_admin_stats():
    from src.api.app import get_store
    from src.api.routes.health import get_process_memory_mb
    store = get_store()

    total = store.count()

    with sqlite_connect(store.fts_store.db_path) as conn:
        c = conn.cursor()
        c.execute("SELECT category, COUNT(*) FROM articles_metadata GROUP BY category")
        categories = dict(c.fetchall())

        c.execute("SELECT status, COUNT(*) FROM articles_metadata GROUP BY status")
        statuses = dict(c.fetchall())

        c.execute("SELECT COUNT(DISTINCT json_extract(json_data, '$.metadata.law_id')) FROM articles_metadata")
        total_docs = c.fetchone()[0]

    return {
        "total_articles": total,
        "total_documents": total_docs,
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
            "icon": "🏛️",
            "description": "O'zbekiston Respublikasi Konstitutsiyasi (Oliy yuridik kuchga ega Bosh qonun)",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "codes": {
            "id": "codes",
            "title": "Kodekslar (Codes)",
            "icon": "📕",
            "description": "O'zbekiston Respublikasining barcha amaldagi 19 ta kodeksi",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "laws": {
            "id": "laws",
            "title": "Qonunlar (Laws - O'RQ)",
            "icon": "📜",
            "description": "O'zbekiston Respublikasining barcha amaldagi qonunlari",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "decrees": {
            "id": "decrees",
            "title": "Prezident Farmonlari (PF)",
            "icon": "🦅",
            "description": "O'zbekiston Respublikasi Prezidentining amaldagi farmonlari",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "resolutions": {
            "id": "resolutions",
            "title": "Prezident va Hukumat Qarorlari (PQ, VMQ)",
            "icon": "🏛️",
            "description": "Vazirlar Mahkamasi va Prezidentning sohalar bo'yicha amaldagi qarorlari",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "regulations": {
            "id": "regulations",
            "title": "Hukumat va Davlat Nizomlari",
            "icon": "📋",
            "description": "Hukumat va idoraviy tasdiqlangan qoidalar, reglamentlar va nizomlar",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "orders": {
            "id": "orders",
            "title": "Vazirlik va Idoralar Buyruqlari",
            "icon": "📑",
            "description": "Adliya vazirligidan ro'yxatdan o'tgan vazirlik va idoraviy normativ buyruqlar",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "parliament": {
            "id": "parliament",
            "title": "Oliy Majlis Qarorlari",
            "icon": "🏛️",
            "description": "Oliy Majlis Qonunchilik palatasi va Senatining normativ qarorlari",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "directives": {
            "id": "directives",
            "title": "Farmoyishlar",
            "icon": "📝",
            "description": "Prezident va Hukumatning normativ xarakterdagi amaldagi farmoyishlari",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "conventions": {
            "id": "conventions",
            "title": "Xalqaro Shartnomalar va Konvensiyalar",
            "icon": "🌐",
            "description": "O'zbekiston ratifikatsiya qilgan xalqaro shartnomalar, bitimlar va konvensiyalar",
            "documents": [],
            "total_articles": 0,
            "total_ru_articles": 0,
        },
        "commentary": {
            "id": "commentary",
            "title": "Huquqiy Sharhlar va Maqolalar",
            "icon": "📚",
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



@router.post("/api/v1/admin/upload", dependencies=_ADMIN)
async def upload_law_file(file: UploadFile = File(...)):
    """Uploads and indexes law files (.json, .txt, or .md)."""
    from src.api.app import get_store, get_client
    store = get_store()
    client = get_client()

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Fayl hajmi 10 MB dan oshmasligi kerak.")
    try:
        text_content = content.decode("utf-8-sig")  # tolerates a UTF-8 BOM
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Fayl UTF-8 kodlashida bo'lishi kerak.")
    filename = file.filename or "unknown.txt"

    indexed_count = 0
    if filename.endswith(".json"):
        try:
            data = json.loads(text_content)
            items = data if isinstance(data, list) else [data]
            for it in items:
                art = CanonicalArticle.model_validate(it)
                await store.index_article(art, client=client)
                indexed_count += 1
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON law format: {str(e)}")
    elif filename.endswith((".txt", ".md")):
        try:
            parsed_articles = parse_law_text_file(text_content, filename)
            for art in parsed_articles:
                await store.index_article(art, client=client)
                indexed_count += 1
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Parsing error: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail="Only .json, .txt, and .md files supported.")

    _invalidate_answer_cache()

    return {
        "status": "success",
        "filename": filename,
        "indexed_articles": indexed_count,
        "message": f"{indexed_count} ta modda muvaffaqiyatli indekslandi."
    }


class IngestUrlRequest(BaseModel):
    url: str
    custom_title: Optional[str] = None
    category: Optional[str] = "commentary"


class PreviewUrlRequest(BaseModel):
    url: str


@router.post("/api/v1/admin/preview-url", dependencies=_ADMIN)
async def preview_web_url(req: PreviewUrlRequest):
    """Previews content, metadata, smart chunks, and cited laws from ANY legal website or Lex.uz."""
    from src.ingestion.web_article_ingester import WebArticleIngester
    from bs4 import BeautifulSoup

    if not req.url:
        raise HTTPException(status_code=400, detail="Havola kiritilmadi.")

    clean_url = req.url.strip()
    try:
        raw_html, final_url = await WebArticleIngester.fetch_page(clean_url)
        soup = BeautifulSoup(raw_html, "html.parser")
        meta = WebArticleIngester.parse_article_metadata(soup, final_url)
        chunks = WebArticleIngester.extract_and_chunk_article(soup, meta)

        all_refs = set()
        for ch in chunks:
            for r in ch.get("refs", []):
                all_refs.add(r)

        return {
            "status": "success",
            "title": meta["title"],
            "domain": meta["domain"],
            "published_date": meta["published_date"],
            "author": meta.get("author", ""),
            "url": final_url,
            "total_chunks": len(chunks),
            "detected_references": sorted(list(all_refs)),
            "preview_chunks": [
                {
                    "heading": ch["heading"],
                    "snippet": ch["text"][:280] + ("..." if len(ch["text"]) > 280 else ""),
                    "refs": ch["refs"],
                }
                for ch in chunks[:4]
            ]
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"URL preview error: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Havolani tahlil qilib bo'lmadi.")


@router.get("/api/v1/admin/ingest-status", dependencies=_ADMIN)
async def get_ingest_status():
    """Returns the current state and progress of the autonomous ingestion engine."""
    from src.ingestion.universal_engine import UniversalAutonomousEngine
    from src.api.app import get_store
    engine = UniversalAutonomousEngine(store=get_store())
    return {
        "status": "active",
        "last_updated": engine.state.last_updated,
        "total_articles": engine.state.total_articles,
        "completed_slugs": engine.state.completed_slugs,
        "failed_slugs": engine.state.failed_slugs,
        "store_count": engine.store.count(),
    }


@router.post("/api/v1/admin/ingest-url", dependencies=_ADMIN)
async def ingest_any_url(req: IngestUrlRequest):
    """Universal endpoint to ingest from ANY legal website (Norma.uz, Advice.uz, Minjust, etc.) or Lex.uz."""
    from src.api.app import get_store, get_client
    import httpx

    if not req.url:
        raise HTTPException(status_code=400, detail="Havola kiritilmadi.")

    clean_url = req.url.strip()
    store = get_store()
    client = get_client()

    # Case A: Lex.uz document URL (host checked strictly) or a bare Doc ID
    if is_lex_uz_url(clean_url) or clean_url.lstrip("-").isdigit():
        from src.ingestion.universal_engine import UniversalAutonomousEngine, DocumentSpec

        # The document ID is the number after /docs/ - not the first digits anywhere in the string
        # (that picked up e.g. the "2" of "www2.lex.uz").
        id_match = re.search(r"/docs/-?(\d+)", clean_url) or re.fullmatch(r"-?(\d+)", clean_url)
        if not id_match:
            raise HTTPException(status_code=400, detail="Lex.uz havolasidan hujjat raqami (ID) aniqlanmadi.")
        doc_id = id_match.group(1)

        # Decide the document type from what the user supplied; the canonical URL built below never contains it.
        looks_like_regulation = any(k in clean_url.lower() for k in ("qaror", "nizom"))
        clean_url = f"https://lex.uz/docs/{doc_id}"

        engine = UniversalAutonomousEngine(store=store, client=client)
        spec = DocumentSpec(
            slug=f"doc_{doc_id}",
            category="regulations" if looks_like_regulation else "laws",
            doc_number=f"Hujjat #{doc_id}",
            title_uz=req.custom_title or f"Lex.uz Hujjat #{doc_id}",
            effective_date="2022-01-01",
            url_uz=clean_url,
            parser_type="regulation_clause" if looks_like_regulation else "statutory_article",
            max_point_number=500,
        )
        try:
            async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as hc:
                count = await engine.ingest_spec(spec, hc, force_reindex=True)

            if count == 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"Hujjat (#{doc_id}) dan birorta ham modda yoki band ajratib olinmadi. Havola yoki hujjat raqamini tekshiring."
                )

            doc_title = spec.title_uz if spec.title_uz and not spec.title_uz.startswith("Lex.uz Hujjat #") else f"Hujjat #{doc_id}"
            _invalidate_answer_cache()
            return {
                "status": "success",
                "source": "lex.uz",
                "indexed_articles": count,
                "url": clean_url,
                "doc_id": doc_id,
                "title": doc_title,
                "message": f"«{doc_title}» hujjatidan {count} ta modda/band Lex.uz dan muvaffaqiyatli yuklandi va indekslandi."
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Lex.uz ingest error for doc {doc_id}: {e}", exc_info=True)
            raise HTTPException(status_code=502, detail="Lex.uz dan hujjatni yuklab bo'lmadi.")

    # Case B: Any external legal portal or news website (Norma.uz, Advice.uz, Minjust.uz, etc.)
    from src.ingestion.web_article_ingester import WebArticleIngester
    try:
        result = await WebArticleIngester.process_and_index_url(
            url=clean_url,
            store=store,
            client=client,
            custom_title=req.custom_title,
            custom_category=req.category or "commentary",
        )
        _invalidate_answer_cache()
        return {
            "status": "success",
            "source": result["domain"],
            "title": result["title"],
            "indexed_articles": result["indexed_count"],
            "url": result["url"],
            "detected_references": result["detected_references"],
            "message": f"'{result['title']}' maqolasi ({result['domain']}) aqlli bo'laklarga ajratilib, {result['indexed_count']} ta tahliliy qism sifatida bazaga kiritildi!"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"External URL ingest error: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Maqolani yuklab bo'lmadi.")


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
