"""
Public read-only browsing of the legal corpus: categories, norms, documents of an act and the corpus statistics.
Questions are answered by POST /api/v1/query (the site) and POST /api/v1/assistant/ask (bots and partners, API key).
"""
import json
import time
from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Query, Request

from src.api.middleware.rate_limiter import limit_public_browsing
from src.domain.disability_taxonomy import CATEGORIES, DISABILITY_GROUPS

router = APIRouter(prefix="/api/v1/inclusive", tags=["Inclusive Legal RAG"])


# --- Public Norms and Categories Metadata ---

@router.get("/categories")
async def get_inclusive_categories():
    """Legal domains and beneficiary groups understood by the query filters."""
    return {
        "categories": [{"id": "all", "name_uz": "Barcha sohalar", "name_ru": "Все сферы"}] + [
            {"id": c.id, "name_uz": c.name_uz, "name_ru": c.name_ru, "description_uz": c.description_uz}
            for c in CATEGORIES
        ],
        "disability_groups": [{"id": "all", "name_uz": "Barcha toifalar"}] + [
            {"id": g.id, "name_uz": g.name_uz} for g in DISABILITY_GROUPS
        ],
    }


def _query_norm_rows(cursor, q: Optional[str], category: Optional[str], limit: int):
    """Runs the norm search with bound parameters; LIKE wildcards typed by the caller are escaped."""
    clauses = []
    params: list = []

    if category and category != "all":
        clauses.append("json_extract(json_data, '$.metadata.category') = ?")
        params.append(category)

    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        clauses.append("(canonical_id LIKE ? ESCAPE '\\' OR json_data LIKE ? ESCAPE '\\')")
        params.extend([like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cursor.execute(
        f"SELECT canonical_id, json_data FROM articles_metadata {where} LIMIT ?",
        (*params, limit),
    )
    return cursor.fetchall()


@router.get("/norms")
def list_inclusive_norms(
    request: Request,
    category: Optional[str] = Query(None, description="Optional category filter"),
    q: Optional[str] = Query(None, max_length=200, description="Search term"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Lists or searches verified statutory norms currently in the inclusive database."""
    limit_public_browsing(request)
    from src.api.app import get_store
    store = get_store()

    with store.fts_store._get_connection() as conn:
        rows = _query_norm_rows(conn.cursor(), q, category, limit)

    results = []
    for cid, j_str in rows:
        try:
            data = json.loads(j_str)
            meta = data.get("metadata", {})
            title_obj = meta.get("article_title", {})
            title = title_obj.get("uz") or title_obj.get("ru") or meta.get("article_number", "")
            law_title_obj = meta.get("law_title", {})
            law_title = law_title_obj.get("uz") or meta.get("law_number", "")
            results.append({
                "canonical_id": cid,
                "article_number": meta.get("article_number", ""),
                "title": title,
                "law_number": meta.get("law_number", ""),
                "law_title": law_title,
                "category": meta.get("category", ""),
                "disability_types": meta.get("disability_types", []),
                "source_url": meta.get("source_url", "https://lex.uz"),
                "status": meta.get("status", "active"),
                "preview": (data.get("translations", {}).get("uz") or "")[:200] + "..."
            })
        except Exception:
            continue

    return {"total": len(results), "norms": results}


@router.get("/documents")
def list_inclusive_documents(
    request: Request,
    q: Optional[str] = Query(None, max_length=200, description="Search keyword in law title, number, authority or norm body"),
    doc_type: Optional[str] = Query(None, description="Document type filter (all, Qonun, Farmon, Qaror, Buyruq, Boshqa)"),
    authority: Optional[str] = Query(None, description="Adopting authority filter"),
):
    """
    Returns grouped list of legal documents directly from the database,
    with auto-detected authority, document type, and norm counts.
    """
    limit_public_browsing(request)
    from src.api.app import get_store
    store = get_store()
    
    # Get all documents without filters to calculate dynamic breakdown counts
    all_docs = store.list_documents()
    filtered_docs = store.list_documents(search_query=q, doc_type=doc_type, authority=authority)

    # Calculate type counts
    type_counts: Dict[str, int] = {"all": len(all_docs)}
    for d in all_docs:
        t = d.get("doc_type", "Boshqa")
        type_counts[t] = type_counts.get(t, 0) + 1

    # Calculate authority counts
    auth_counts: Dict[str, int] = {"all": len(all_docs)}
    for d in all_docs:
        a = d.get("authority", "Boshqa davlat organi")
        auth_counts[a] = auth_counts.get(a, 0) + 1

    return {
        "total": len(filtered_docs),
        "documents": filtered_docs,
        "type_counts": type_counts,
        "authority_counts": auth_counts,
    }


@router.get("/documents/{law_identifier}/norms")
def get_document_norms(request: Request, law_identifier: str):
    """
    Returns all statutory norms and articles belonging to a specific legal document.
    """
    limit_public_browsing(request)
    import urllib.parse
    from src.api.app import get_store
    from src.storage.fts_store import detect_authority_and_type
    store = get_store()

    norms = store.get_articles_by_law(law_identifier)
    if not norms:
        decoded = urllib.parse.unquote(law_identifier)
        norms = store.get_articles_by_law(decoded)

    if not norms:
        raise HTTPException(status_code=404, detail="Hujjat yoki unga tegishli normalar topilmadi.")

    first_norm = norms[0]
    auth, dtype = detect_authority_and_type(first_norm.get("law_number"), first_norm.get("law_title"))

    return {
        "law_number": first_norm.get("law_number"),
        "law_title": first_norm.get("law_title"),
        "authority": auth,
        "doc_type": dtype,
        "source_url": first_norm.get("source_url"),
        "total_norms": len(norms),
        "norms": norms,
    }


@router.get("/stats")
def get_system_stats(request: Request):
    """Returns database size and norms count. The keys of the partners are administrative: see the Integratsiyalar page."""
    limit_public_browsing(request)
    from src.api.app import get_store
    store = get_store()
    with store.fts_store._get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT 
                COUNT(*), 
                COUNT(DISTINCT json_extract(json_data, '$.metadata.law_id')) 
            FROM articles_metadata
            WHERE (json_extract(json_data, '$.metadata.source_type') = 'lex' OR json_extract(json_data, '$.metadata.source_type') IS NULL)
              AND canonical_id NOT LIKE 'hp_%' AND canonical_id NOT LIKE 'qa_%'
        """)
        row = c.fetchone()
        total_norms = row[0] if row else 0
        total_docs = row[1] if row else 0

        c.execute("""
            SELECT json_extract(json_data, '$.metadata.category'), COUNT(*) 
            FROM articles_metadata 
            WHERE (json_extract(json_data, '$.metadata.source_type') = 'lex' OR json_extract(json_data, '$.metadata.source_type') IS NULL)
              AND canonical_id NOT LIKE 'hp_%' AND canonical_id NOT LIKE 'qa_%'
            GROUP BY 1
        """)
        cat_distribution = {row[0]: row[1] for row in c.fetchall() if row[0]}

    return {
        "status": "healthy",
        "total_statutory_norms": total_norms,
        "total_documents": total_docs,
        "database_storage": "Clean Inclusive SQLite + FTS5 + LanceDB",
        "category_distribution": cat_distribution,
        "timestamp": time.time(),
    }
