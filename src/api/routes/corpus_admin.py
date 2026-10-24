"""
Corpus Administration Routes: Lex.uz Preview, Add, and Refresh Background Jobs.
All operations require administrator access.
"""
import asyncio
import json
import logging
import re
import sys
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth.admin import require_admin
from src.ingestion.lex_client import LexClient
from src.ingestion.lex_structured import LexDocumentParser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/corpus", tags=["Corpus Admin"])
_ADMIN = [Depends(require_admin)]

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RAW_CACHE_DIR = "data/raw_lex"


def _invalidate_answer_cache() -> None:
    try:
        from src.api.app import get_cache
        get_cache().clear()
    except Exception as e:
        logger.warning(f"Could not clear query cache: {e}")


def _invalidate_article_cache() -> None:
    """The build script runs in a subprocess and writes to the database behind this process's back."""
    try:
        from src.api.app import get_store
        get_store().fts_store.clear_article_cache()
    except Exception as e:
        logger.warning(f"Could not clear article cache: {e}")


def _latin_edition(lex: LexClient, parser: LexDocumentParser, doc_id: str) -> str:
    raw = str(doc_id).strip()
    if raw.startswith("-"):
        return raw
    if lex.fetch_url(f"https://lex.uz/uz/docs/-{raw}"):
        return f"-{raw}"
    html = lex.fetch_url(f"https://lex.uz/uz/docs/{raw}")
    if not html:
        return ""
    parsed = parser.parse(html, raw)
    lat_link = parsed.language_links.get("uz_latn", "")
    m = re.search(r"/docs/(-?\d+)", lat_link)
    return m.group(1) if m else ""


_LEX_ID = re.compile(r"-?[0-9]{3,9}")          # ASCII digits only: the id ends up in a Lex.uz URL and a CLI argument


def parse_source_to_id(source: str) -> str:
    s = (source or "").strip()
    if _LEX_ID.fullmatch(s):
        return s
    if s.startswith("https://"):
        try:
            parsed = urllib.parse.urlparse(s)
            if parsed.hostname in ("lex.uz", "www.lex.uz"):
                m = re.search(r"/docs/(-?[0-9]+)", parsed.path)
                if m and _LEX_ID.fullmatch(m.group(1)):
                    return m.group(1)
        except Exception:
            pass
    raise HTTPException(
        status_code=422,
        detail="Faqat Lex.uz ID raqami (3-9 xonali) yoki https://lex.uz/... havolasi qabul qilinadi."
    )


# --- Job Registry & Worker ---

_jobs: Dict[str, dict] = {}
_current_active_job_id: Optional[str] = None
_job_lock = asyncio.Lock()
_background_tasks: set = set()                 # strong references: an unreferenced task can be garbage-collected
_MAX_JOBS_KEPT = 50
_REGISTRY = _PROJECT_ROOT / "data" / "sources" / "disability_registry.json"


def _registry_entry(lex_id: str) -> Optional[dict]:
    try:
        docs = json.loads(_REGISTRY.read_text(encoding="utf-8")).get("documents", [])
    except (OSError, ValueError):
        return None
    return next((d for d in docs if d.get("lex_id") == lex_id), None)


def _valid_lex_id(raw: str) -> str:
    clean = (raw or "").strip()
    if not _LEX_ID.fullmatch(clean):
        raise HTTPException(status_code=422, detail="Noto'g'ri Lex.uz ID formati.")
    return clean


def _start_job(job_id: str, coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    for old in list(_jobs)[:-_MAX_JOBS_KEPT]:
        if _jobs[old].get("status") != "running":
            _jobs.pop(old, None)


async def _run_corpus_subprocess(
    job_id: str,
    action: str,
    lex_id: str,
    include: Optional[str] = None
) -> None:
    global _current_active_job_id
    script_path = str(_PROJECT_ROOT / "scripts" / "build_disability_corpus.py")
    summary_text = None

    try:
        if action == "add":
            _jobs[job_id]["step"] = "adding"
            cmd_add = [
                sys.executable,
                script_path,
                "add",
                f"--lex-id={lex_id}",
                f"--include={include or 'all'}",
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd_add,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_PROJECT_ROOT),
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=1200)
            except asyncio.TimeoutError:
                proc.kill()
                raise RuntimeError("Hujjatni qo'shish vaqti tugadi (timeout: 20 daqiqa).")

            if proc.returncode != 0:
                err_msg = stderr_bytes.decode("utf-8", errors="replace").strip() or stdout_bytes.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Hujjatni reestrga qo'shishda xatolik: {err_msg}")

        # Refresh step
        _jobs[job_id]["step"] = "refreshing"
        cmd_refresh = [
            sys.executable,
            script_path,
            "refresh",
            f"--law-ids={lex_id}",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd_refresh,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_PROJECT_ROOT),
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=1200)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("Hujjatni indekslash/yangilash vaqti tugadi (timeout: 20 daqiqa).")

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            err_msg = stderr_text.strip() or stdout_text.strip()
            raise RuntimeError(f"Hujjatni yangilashda xatolik: {err_msg}")

        # Extract summary: "refresh: N docs, M changed/new indexed, K removed"
        # the script logs to stderr (logging), so the summary line is looked up in both streams
        match = re.search(r"refresh:\s*\d+\s+docs,\s*\d+\s+changed/new indexed,\s*\d+\s+removed.*",
                          stdout_text + "\n" + stderr_text)
        if match:
            summary_text = match.group(0).split("->")[0].strip()
        else:
            summary_text = "Hujjat muvaffaqiyatli yangilandi va indekslandi."

        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["step"] = "completed"
        _jobs[job_id]["summary"] = summary_text
        _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()

    except Exception as e:
        logger.error(f"Corpus background job {job_id} failed: {e}", exc_info=True)
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)
        _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
    finally:
        # also after a failed job: the script may have written part of the corpus before it stopped
        _invalidate_article_cache()
        _invalidate_answer_cache()
        async with _job_lock:
            if _current_active_job_id == job_id:
                _current_active_job_id = None


# --- Schemas ---

class CorpusPreviewRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=2048)


class CorpusPreviewResponse(BaseModel):
    lex_id: str
    number: str
    title: str
    doc_type: str
    adopted: str
    status: str
    units: int
    in_registry: bool
    include: str
    is_amending: bool = False


# an act that only amends or repeals others: Lex.uz already shows its changes inside the acts it amends
_AMENDING_TITLE = re.compile(
    r"o['ʻʼ‘’`]?zgartish|o['ʻʼ‘’`]?zgartirish|qo['ʻʼ‘’`]?shimcha(lar)? kiritish|o['ʻʼ‘’`]?z kuchini yo['ʻʼ‘’`]?qotgan deb topish",
    re.IGNORECASE)


class CorpusAddRequest(BaseModel):
    lex_id: str = Field(..., min_length=1, max_length=50)
    include: Literal["all", "disability_articles"] = "all"


class CorpusRefreshRequest(BaseModel):
    lex_id: str = Field(..., min_length=1, max_length=50)


class CorpusJobResponse(BaseModel):
    job_id: str
    status: Literal["running", "done", "failed"]
    step: Optional[str] = None
    summary: Optional[str] = None
    error: Optional[str] = None
    started_at: str
    finished_at: Optional[str] = None


# --- Endpoints ---

def _fetch_preview(raw_id: str, parser: LexDocumentParser):
    """(Lex id, parsed document). The Lex client is synchronous (blocking HTTP, sleeps between retries): call this in a thread."""
    with LexClient(cache_dir=_RAW_CACHE_DIR) as lex:
        latin_id = _latin_edition(lex, parser, raw_id) or (raw_id if raw_id.startswith("-") else f"-{raw_id}")
        html = lex.fetch_document(latin_id)
        if not html:
            raise HTTPException(status_code=404, detail=f"Hujjat Lex.uz'da topilmadi: {latin_id}")
        return latin_id, parser.parse(html, latin_id)


@router.post("/preview", response_model=CorpusPreviewResponse, dependencies=_ADMIN)
async def preview_corpus_document(payload: CorpusPreviewRequest):
    """
    Parses and previews an official legal document from Lex.uz without adding it to the corpus.
    Accepts 3-9 digit Lex.uz ID or https://(www.)lex.uz/docs/<id> URL.
    """
    raw_id = parse_source_to_id(payload.source)
    parser = LexDocumentParser()

    try:
        latin_id, doc = await asyncio.to_thread(_fetch_preview, raw_id, parser)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching preview from Lex.uz for id {raw_id}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Lex.uz dan hujjatni o'qib bo'lmadi: {e}")

    entry = _registry_entry(latin_id)
    in_registry = entry is not None
    include_mode = (entry or {}).get("include", "all")

    return CorpusPreviewResponse(
        lex_id=latin_id,
        number=doc.number or "",
        title=doc.title or "",
        doc_type=doc.doc_type or "",
        adopted=doc.adopted_date or "",
        status=doc.status or "active",
        units=len(doc.units),
        in_registry=in_registry,
        include=include_mode,
        is_amending=bool(_AMENDING_TITLE.search(doc.title or "")),
    )


@router.post("/add", dependencies=_ADMIN)
async def start_corpus_add_job(payload: CorpusAddRequest):
    """
    Enqueues a background job to add a new document from Lex.uz to the registry and refresh it into the store.
    Only one background job can run at a time.
    """
    global _current_active_job_id
    clean_id = _valid_lex_id(payload.lex_id)

    async with _job_lock:
        if _current_active_job_id and _jobs.get(_current_active_job_id, {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="Boshqa korpus yangilash vazifasi bajarilmoqda.")

        job_id = f"job_{uuid.uuid4().hex[:12]}"
        _current_active_job_id = job_id
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "step": "queued",
            "summary": None,
            "error": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }

    _start_job(job_id, _run_corpus_subprocess(job_id, action="add", lex_id=clean_id, include=payload.include))

    return {"status": "accepted", "job_id": job_id}


@router.post("/refresh", dependencies=_ADMIN)
async def start_corpus_refresh_job(payload: CorpusRefreshRequest):
    """
    Enqueues a background job to refresh an existing document from Lex.uz into the store.
    Only one background job can run at a time.
    """
    global _current_active_job_id
    clean_id = _valid_lex_id(payload.lex_id)
    if _registry_entry(clean_id) is None:
        raise HTTPException(status_code=404, detail="Bu hujjat reestrda yo'q: avval \"Lex.uz'dan hujjat qo'shish\" orqali qo'shing.")

    async with _job_lock:
        if _current_active_job_id and _jobs.get(_current_active_job_id, {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="Boshqa korpus yangilash vazifasi bajarilmoqda.")

        job_id = f"job_{uuid.uuid4().hex[:12]}"
        _current_active_job_id = job_id
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "step": "queued",
            "summary": None,
            "error": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }

    _start_job(job_id, _run_corpus_subprocess(job_id, action="refresh", lex_id=clean_id))

    return {"status": "accepted", "job_id": job_id}


@router.get("/jobs/{job_id}", response_model=CorpusJobResponse, dependencies=_ADMIN)
async def get_corpus_job_status(job_id: str):
    """
    Returns the status and summary/error of a corpus background job.
    """
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Bunday vazifa topilmadi.")
    return _jobs[job_id]
