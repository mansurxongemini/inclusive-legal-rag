import logging
from pathlib import Path
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from src.api.auth.admin import require_admin
from src.storage.sqlite_utils import connect as sqlite_connect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin"])

# Static HTML pages stay public; every /api/v1/admin/* route requires administrator access.
_ADMIN = [Depends(require_admin)]


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


