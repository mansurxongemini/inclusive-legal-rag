"""
Inclusive Legal RAG - Public Integration API & Admin Control Routes.
Exclusively serving legal rights, benefits, and statutory procedures for Persons with Disabilities.
"""
import asyncio
from datetime import datetime, timezone
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.domain.disability_taxonomy import CATEGORIES, CATEGORY_IDS, DISABILITY_GROUPS


from src.nlp.query_analyzer import QueryAnalyzer
from src.retrieval.pipeline import retrieve_contexts
from src.generation.generator import AnswerGenerator
from src.generation.validator import CitationItem
from src.api.middleware.security import sanitize_user_input
from src.api.middleware.rate_limiter import rate_limiter
from src.api.auth.admin import is_direct_loopback, require_admin
from src.api.auth.api_keys import api_key_manager, ApiKeyRecord
from src.ingestion.file_importer import LocalFileImporter, BatchFileImportReport
from src.ingestion.document_inspector import DocumentInspector, DocumentInspectionReport
from src.clients.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/inclusive", tags=["Inclusive Legal RAG"])

# Every route that changes the corpus, manages keys or runs paid/diagnostic jobs is administrator-only.
_ADMIN = [Depends(require_admin)]

# Bulk file import is confined to the project's data directory (no arbitrary filesystem reads).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = (_PROJECT_ROOT / "data").resolve()
_DEFAULT_IMPORT_DIR = "data/qonunlar"


def _resolve_import_dir(directory_path: str) -> Path:
    raw = Path(directory_path or _DEFAULT_IMPORT_DIR)
    candidate = (raw if raw.is_absolute() else _PROJECT_ROOT / raw).resolve()
    if candidate != _DATA_ROOT and _DATA_ROOT not in candidate.parents:
        raise HTTPException(
            status_code=400,
            detail="Papka faqat loyihaning data/ katalogi ichida bo'lishi mumkin.",
        )
    return candidate


def _invalidate_answer_cache() -> None:
    """Cached answers describe the corpus as it was; drop them whenever norms change."""
    from src.api.app import get_cache
    try:
        get_cache().clear()
    except Exception as e:  # cache is an optimization, never fail the write because of it
        logger.warning(f"Could not clear query cache: {e}")


# --- Request and Response Schemas ---

class InclusiveQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000, description="Legal question regarding disability rights, pensions, employment, TMEK, or benefits")
    disability_group: str = Field(
        default="all",
        description="Target beneficiary group to prioritize relevant benefits (see /categories)"
    )
    category: str = Field(default="all", description="Legal domain filter (see /categories)")

    @field_validator("disability_group")
    @classmethod
    def _check_group(cls, v: str) -> str:
        if v not in {"all", "general", *(g.id for g in DISABILITY_GROUPS)}:
            raise ValueError("unknown disability_group")
        return v

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        if v != "all" and v not in CATEGORY_IDS:
            raise ValueError("unknown category")
        return v

    language: Literal["auto", "uz", "ru", "en"] = Field(default="auto", description="Preferred response language")
    mode: Literal["plain", "legal_text", "easy_read"] = Field(default="plain", description="plain language summary, verbatim legal text, or easy-read (very short sentences)")


class InclusiveQueryResponse(BaseModel):
    answer: str
    clean_answer: str
    telegram_formatted: str
    citations: List[CitationItem]
    detected_language: str
    detected_script: str
    category: str
    disability_group: str
    validation_passed: bool
    is_refusal: bool
    cached: bool = False
    response_time_ms: float = 0.0
    retrieval_confidence: Optional[float] = None
    status_warnings: List[dict] = []


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Name of external service or developer (e.g. 'Toshkent Inclusive Bot')")
    rate_limit_per_min: int = Field(default=60, ge=1, le=10000, description="Rate limit per minute")


class InspectUrlRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="Lex.uz URL to inspect and visualize")


class TestVectorRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000, description="Text payload to generate BGE-M3 vector for")


class TestJevRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000, description="Statutory clause text to classify with TypeSafe Jev 1.13")
    law_title: Optional[str] = Field(default=None, description="Optional parent law title")





# --- Authentication Dependency ---

def authenticate_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
) -> Optional[ApiKeyRecord]:
    token = x_api_key
    if not token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() in ["bearer", "token"]:
            token = parts[1]

    # The local dashboard (direct loopback connection, no proxy headers) may query without a key.
    # The Referer header is client-controlled and must never grant access.
    if not token:
        if is_direct_loopback(request):
            return None
        raise HTTPException(
            status_code=401,
            detail="API kaliti talab qilinadi. X-API-Key sarlavhasi orqali kalitingizni yuboring."
        )

    record = api_key_manager.validate_key(token)
    if not record:
        raise HTTPException(
            status_code=403,
            detail="Yaroqsiz yoki bekor qilingan API kaliti."
        )
    return record


# --- Primary Query Endpoints ---

@router.post("/query", response_model=InclusiveQueryResponse)
async def query_inclusive_rag(
    request: Request,
    payload: InclusiveQueryRequest,
    stream: bool = Query(default=False, description="Stream response tokens via SSE"),
    auth: Optional[ApiKeyRecord] = Depends(authenticate_api_key),
):
    """
    Primary endpoint for third-party bots, mobile apps, and inclusive portals.
    Answers legal questions strictly grounded in Uzbekistan's disability legislation.
    """
    start_time = time.time()
    if auth is not None:
        rate_limiter.check(request, key=f"apikey:{auth.key_id}", limit=auth.rate_limit_per_min)
    else:
        rate_limiter.check(request)

    cleaned_query = sanitize_user_input(payload.question)
    if not cleaned_query:
        raise HTTPException(status_code=422, detail="Savol matni bo'sh bo'lishi mumkin emas.")

    from src.api.app import get_store, get_cache, get_client
    store = get_store()
    cache = get_cache()
    client = get_client()

    user_lang = None if payload.language == "auto" else payload.language
    analysis = QueryAnalyzer.analyze(cleaned_query, user_language=user_lang)
    target_language = analysis.detected_language

    # Inject explicit disability group if selected by client
    if payload.disability_group != "all":
        if payload.disability_group not in analysis.extracted_disability_types:
            analysis.extracted_disability_types.append(payload.disability_group)

    # 1. Dual-layer caching check
    cache_key = f"{cleaned_query}_{payload.disability_group}_{payload.category}"
    if not stream:
        cached_resp = cache.get(cache_key, target_language, payload.mode)
        if cached_resp:
            cached_resp["cached"] = True
            cached_resp["response_time_ms"] = round((time.time() - start_time) * 1000, 2)
            return cached_resp

    # 2-4. Hybrid retrieval, category focus, cross-references, status filter, rerank, relevance gate
    retrieval = await retrieve_contexts(
        analysis=analysis,
        store=store,
        client=client,
        top_k=25,
        max_extra=6,
        rerank_top_n=6,
        category=payload.category,
    )
    final_contexts = retrieval.contexts

    # 4. Generation
    generator = AnswerGenerator(client=client)

    if stream:
        return StreamingResponse(
            generator.generate_answer_stream(
                query=cleaned_query,
                contexts=final_contexts,
                language=target_language,
                mode=payload.mode,
            ),
            media_type="text/event-stream"
        )

    try:
        gen_result = await generator.generate_answer(
            query=cleaned_query,
            contexts=final_contexts,
            language=target_language,
            mode=payload.mode,
        )
    except RuntimeError as e:
        logger.error(f"Answer generation unavailable: {e}")
        raise HTTPException(
            status_code=503,
            detail="Javob yaratish xizmati vaqtincha mavjud emas. Iltimos, birozdan so'ng qayta urinib ko'ring.",
        )

    elapsed_ms = round((time.time() - start_time) * 1000, 2)

    response_payload = InclusiveQueryResponse(
        answer=gen_result.clean_answer or gen_result.answer,
        clean_answer=gen_result.clean_answer or gen_result.answer,
        telegram_formatted=gen_result.telegram_formatted or gen_result.answer,
        citations=gen_result.citations,
        detected_language=target_language,
        detected_script=analysis.detected_script,
        category=payload.category,
        disability_group=payload.disability_group,
        validation_passed=gen_result.validation_passed,
        is_refusal=gen_result.is_refusal,
        cached=False,
        response_time_ms=elapsed_ms,
        retrieval_confidence=round(retrieval.decision.confidence, 3) if retrieval.decision else None,
        status_warnings=retrieval.status_warnings,
    )

    # Cache only verified, substantive answers
    if (
        response_payload.validation_passed
        and not response_payload.is_refusal
        and len((response_payload.clean_answer or response_payload.answer).strip()) > 80
    ):
        cache.set(
            cache_key,
            target_language,
            payload.mode,
            response_payload.model_dump()
        )

    return response_payload


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
async def list_inclusive_norms(
    category: Optional[str] = Query(None, description="Optional category filter"),
    q: Optional[str] = Query(None, max_length=200, description="Search term"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Lists or searches verified statutory norms currently in the inclusive database."""
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
async def list_inclusive_documents(
    q: Optional[str] = Query(None, max_length=200, description="Search keyword in law title, number, authority or norm body"),
    doc_type: Optional[str] = Query(None, description="Document type filter (all, Qonun, Farmon, Qaror, Buyruq, Boshqa)"),
    authority: Optional[str] = Query(None, description="Adopting authority filter"),
):
    """
    Returns grouped list of legal documents directly from the database,
    with auto-detected authority, document type, and norm counts.
    """
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
async def get_document_norms(law_identifier: str):
    """
    Returns all statutory norms and articles belonging to a specific legal document.
    """
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
async def get_system_stats():
    """Returns database size, norms count, and API key metrics."""
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

    api_keys = api_key_manager.list_keys()
    total_requests = sum(k.total_requests for k in api_keys)

    return {
        "status": "healthy",
        "total_statutory_norms": total_norms,
        "total_documents": total_docs,
        "database_storage": "Clean Inclusive SQLite + FTS5 + LanceDB",
        "category_distribution": cat_distribution,
        "active_api_keys": len([k for k in api_keys if k.is_active]),
        "total_api_requests_served": total_requests,
        "timestamp": time.time(),
    }


# --- Administration: Ingestion (URL & Local Folder) & Manual Upload ---



@router.post("/admin/inspect-document", dependencies=_ADMIN, response_model=DocumentInspectionReport)
async def inspect_document(payload: InspectUrlRequest):
    """Parses and visualizes how a Lex.uz document and its tables are structured and sent to BGE-M3."""
    inspector = DocumentInspector()
    try:
        return await inspector.inspect_url(payload.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error inspecting document {payload.url}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Hujjatni tahlil qilib bo'lmadi. Keyinroq qayta urinib ko'ring.")


@router.post("/admin/test-vector", dependencies=_ADMIN)
async def test_vector(payload: TestVectorRequest):
    """Calculates live BGE-M3 vector embedding for any text payload and returns coordinates."""
    from src.api.app import get_client
    client = get_client()
    t0 = time.time()
    try:
        embeddings = await client.get_embeddings([payload.text])
    except RuntimeError as e:
        logger.error(f"Embedding service unavailable: {e}")
        raise HTTPException(status_code=503, detail="Embedding xizmati vaqtincha mavjud emas.")
    dur = (time.time() - t0) * 1000
    vec = embeddings[0] if embeddings else []
    norm = sum(x * x for x in vec) ** 0.5 if vec else 0.0
    return {
        "dimensions": len(vec),
        "norm": round(norm, 4),
        "sample_coordinates": [round(x, 5) for x in vec[:15]],
        "duration_ms": round(dur, 1),
    }


@router.post("/admin/test-jev", dependencies=_ADMIN, response_model=None)
async def test_jev_decision(payload: TestJevRequest):
    """Runs TypeSafe Jev 1.13 decision engine on statutory clause for category, score, and relevance."""
    from src.ingestion.jev_classifier import JevLegalClassifier
    classifier = JevLegalClassifier()
    try:
        return await classifier.classify_clause(payload.text, payload.law_title)
    except Exception as e:
        logger.error(f"Error running Jev decision: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Tahlilni bajarishda ichki xatolik yuz berdi.")


@router.post("/admin/sync", dependencies=_ADMIN)
async def legacy_sync_alias():
    """Legacy alias, executes safe local folder scanning without crawler 404s."""
    from src.api.app import get_store
    importer = LocalFileImporter(store=get_store())
    report = await importer.scan_and_import_directory(str(_resolve_import_dir(_DEFAULT_IMPORT_DIR)))
    _invalidate_answer_cache()
    return {
        "success": report.success,
        "total_ingested": report.total_articles_indexed,
        "message": report.message
    }




# --- Administration: API Keys Management ---

@router.get("/admin/api-keys", dependencies=_ADMIN)
async def get_api_keys():
    """Lists all active and revoked API keys."""
    return {"api_keys": [k.model_dump() for k in api_key_manager.list_keys()]}


@router.post("/admin/api-keys", dependencies=_ADMIN)
async def create_new_api_key(payload: ApiKeyCreateRequest):
    """Creates a new API key for a developer or bot."""
    new_key = api_key_manager.create_key(payload.name, payload.rate_limit_per_min)
    return {
        "success": True,
        "message": "Yangi API kaliti muvaffaqiyatli yaratildi. Uni nusxalab oling, kalit qayta to'liq ko'rsatilmaydi.",
        "key": new_key,
    }


@router.delete("/admin/api-keys/{key_id}", dependencies=_ADMIN)
async def revoke_existing_api_key(key_id: str):
    """Revokes an API key."""
    revoked = api_key_manager.revoke_key(key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API kaliti topilmadi")
    return {"success": True, "message": f"{key_id} kaliti bekor qilindi."}
