import asyncio
import logging

from src.runtime_tuning import tune_malloc

tune_malloc()      # before any worker thread exists; see src/runtime_tuning.py

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import removed_settings_in_use, settings
from src.logging_setup import configure_logging
from src.storage.hybrid_store import HybridStore
from src.api.cache import QueryCache
from src.clients.openrouter import OpenRouterClient
from src.api.routes import query, article, feedback, health, admin, inclusive_api, webhooks, huquqplus_admin, corpus_admin
from src.editorial.router import router as editorial_router
from src.api.middleware.hardening import BodyLimitMiddleware, SecurityHeadersMiddleware

configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Global instances
_store: Optional[HybridStore] = None
_cache: Optional[QueryCache] = None
_client: Optional[OpenRouterClient] = None


def get_store() -> HybridStore:
    global _store
    if _store is None:
        _store = HybridStore()
        # Importers and admin routes index through this store; reuse the app's single HTTP client.
        _store._default_client = get_client()
    return _store


def get_cache() -> QueryCache:
    global _cache
    if _cache is None:
        _cache = QueryCache()
    return _cache


def get_client() -> OpenRouterClient:
    global _client
    if _client is None:
        _client = OpenRouterClient()
    return _client


async def _run_huquqplus_scheduler():
    from src.integrations.huquqplus_sync import full_sync, process_queue
    logger.info("Huquq+ rejalashtiruvchisi ishga tushdi.")
    last_full_sync = 0.0
    full_interval_s = max(60, settings.HUQUQPLUS_SYNC_INTERVAL_MIN * 60)

    while True:
        try:
            # 1. Navbatni tekshirish (har 20 soniyada)
            try:
                await process_queue(limit=50)
            except Exception as e:
                logger.error(f"Huquq+ process_queue xatosi: {e}")

            # 2. To'liq sinxronlash (har HUQUQPLUS_SYNC_INTERVAL_MIN da)
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now - last_full_sync >= full_interval_s:
                last_full_sync = now
                try:
                    await full_sync()
                except Exception as e:
                    logger.error(f"Huquq+ full_sync xatosi: {e}")

            await asyncio.sleep(20)
        except asyncio.CancelledError:
            logger.info("Huquq+ rejalashtiruvchisi to'xtatildi.")
            break
        except Exception as e:
            logger.error(f"Huquq+ rejalashtiruvchisi kutilmagan xatosi: {e}")
            await asyncio.sleep(20)


async def _run_assistant_maintenance_scheduler():
    from src.gateway.conversations import get_conversation_store
    logger.info("Assistant API jurnallari tozalash rejalashtiruvchisi ishga tushdi.")
    while True:
        try:
            days = getattr(settings, "ASSISTANT_LOG_RETENTION_DAYS", 90)
            await asyncio.to_thread(get_conversation_store().purge_older_than, days)
            removed = await asyncio.to_thread(get_cache().purge_expired)
            logger.info(f"Answer cache: {removed} expired entries removed")
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            logger.info("Assistant API jurnallari tozalash rejalashtiruvchisi to'xtatildi.")
            break
        except Exception as e:
            logger.error(f"Assistant API purge xatosi: {e}")
            await asyncio.sleep(3600)


async def _run_vector_maintenance():
    """
    LanceDB keeps every version of the table (each upsert, re-embedding or sync write makes one): without cleanup the folder grew to
    1.8 GB for 150 MB of vectors. Compacts and prunes versions older than VECTOR_KEEP_VERSIONS_HOURS once a day.
    """
    from datetime import timedelta
    await asyncio.sleep(300)
    while True:
        try:
            result = await asyncio.to_thread(
                get_store().vector_store.optimize, timedelta(hours=settings.VECTOR_KEEP_VERSIONS_HOURS))
            logger.info(f"Vector table maintenance: {result}")
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Vector table maintenance failed: {e}")
            await asyncio.sleep(3600)


async def _run_provider_limit_poll():
    """Reads the remaining USD of the OpenRouter key every 15 minutes (a free call) so that the budget guard knows the
    key's own limit and not only what this service has spent."""
    from src.clients.spend import ledger
    while True:
        try:
            if not get_client().embedding_is_mock:
                remaining = await ledger.refresh_provider_limit(get_client())
                if remaining is not None and remaining < 1.0:
                    logger.warning(f"The OpenRouter key has ${remaining:.2f} left")
            await asyncio.sleep(900)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Provider limit poll failed: {e}")
            await asyncio.sleep(900)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure directories & seed pilot dataset if empty
    settings.ensure_directories()
    if settings.is_mock_mode and not settings.MOCK_EXTERNAL_APIS:
        logger.warning(
            "OPENROUTER_API_KEY is not set: running in MOCK mode. Answers are deterministic placeholders, "
            "not real legal analysis. Configure the key (or set MOCK_EXTERNAL_APIS=true to silence this)."
        )
    stale = removed_settings_in_use()
    if stale:
        logger.warning(
            f"These settings are no longer read: {', '.join(stale)}. They belonged to the Meta test provider (one "
            "OPENROUTER_API_KEY and OPENROUTER_BASE_URL serve every call now) or to experiments that were dropped; remove them from .env."
        )
    if not settings.is_mock_mode and "openrouter.ai" not in settings.OPENROUTER_BASE_URL:
        logger.warning(
            f"OPENROUTER_BASE_URL is {settings.OPENROUTER_BASE_URL}: the service is built for OpenRouter "
            "(https://openrouter.ai/api/v1) for chat, embeddings and Jev, and models are named as OpenRouter names them."
        )
    if settings.admin_loopback_enabled and settings.HOST not in ("127.0.0.1", "::1", "localhost"):
        logger.warning(
            "Administration is open to direct local connections without a key. Behind a reverse proxy that does not "
            "forward X-Forwarded-For/X-Real-IP every visitor looks local: set ADMIN_LOOPBACK_ENABLED=false and ADMIN_API_KEY."
        )
    store = get_store()
    client = get_client()

    if store.count() == 0:
        pilot_file = _PROJECT_ROOT / "data" / "pilot_laws" / "law_disability_2020.json"
        if pilot_file.exists():
            logger.info("Initializing knowledge base with pilot disability rights law...")
            await store.seed_from_file(str(pilot_file), client=client)

    sync_task: Optional[asyncio.Task] = None
    if settings.HUQUQPLUS_SYNC_ENABLED and not settings.MOCK_EXTERNAL_APIS:
        sync_task = asyncio.create_task(_run_huquqplus_scheduler())

    # Daily assistant maintenance (answers/turns/feedback purge)
    purge_task = asyncio.create_task(_run_assistant_maintenance_scheduler())
    limit_task = asyncio.create_task(_run_provider_limit_poll())
    maintenance_task = asyncio.create_task(_run_vector_maintenance())

    yield

    # Shutdown: cancel every background task and wait until each has really stopped
    background = [t for t in (sync_task, purge_task, limit_task, maintenance_task) if t]
    for task in background:
        task.cancel()
    await asyncio.gather(*background, return_exceptions=True)

    if _client:
        await _client.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Uzbekistan Legal RAG API",
        description="Production-grade, ultra-accurate Multilingual Legal RAG Platform for Uzbekistan Legislation",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Outermost first: headers on every response, then the body limit, then CORS
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    # Enable CORS (no cookies are used, so credentialed cross-origin requests are not needed)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Custom exception handlers for /api/v1/assistant and /api/v1/openai prefixes
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.requests import Request as StarletteRequest

    @app.exception_handler(StarletteHTTPException)
    async def custom_http_exception_handler(request: StarletteRequest, exc: StarletteHTTPException):
        path = request.url.path
        if path.startswith("/api/v1/assistant"):
            if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
                content = {"error": {"code": exc.detail["code"], "message": exc.detail["message"]}}
            else:
                code = "not_found" if exc.status_code == 404 else ("invalid_request" if exc.status_code == 422 else ("service_unavailable" if exc.status_code == 503 else "error"))
                content = {"error": {"code": code, "message": str(exc.detail)}}
            return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)
        elif path.startswith("/api/v1/openai"):
            if isinstance(exc.detail, dict) and "error" in exc.detail:
                content = exc.detail
            elif isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
                content = {"error": {"message": exc.detail["message"], "type": "invalid_request_error", "code": exc.detail["code"]}}
            else:
                code = "not_found" if exc.status_code == 404 else "invalid_request_error"
                content = {"error": {"message": str(exc.detail), "type": "invalid_request_error", "code": code}}
            return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)
        from fastapi.exception_handlers import http_exception_handler as default_http_handler
        return await default_http_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def custom_validation_exception_handler(request: StarletteRequest, exc: RequestValidationError):
        path = request.url.path
        if path.startswith("/api/v1/assistant"):
            msgs = []
            for err in exc.errors():
                loc = ".".join(str(x) for x in err.get("loc", []) if x not in ("body",))
                msg = err.get("msg", "")
                msgs.append(f"{loc}: {msg}" if loc else msg)
            err_msg = "; ".join(msgs) if msgs else "So'rov maydonlarida xatolik bor."
            return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": err_msg}})
        elif path.startswith("/api/v1/openai"):
            msgs = []
            for err in exc.errors():
                loc = ".".join(str(x) for x in err.get("loc", []) if x not in ("body",))
                msg = err.get("msg", "")
                msgs.append(f"{loc}: {msg}" if loc else msg)
            err_msg = "; ".join(msgs) if msgs else "So'rov maydonlarida xatolik bor."
            return JSONResponse(status_code=422, content={"error": {"message": err_msg, "type": "invalid_request_error", "code": "invalid_request"}})
        from fastapi.exception_handlers import request_validation_exception_handler as default_val_handler
        return await default_val_handler(request, exc)

    # Mount static files for admin panel
    from fastapi.staticfiles import StaticFiles

    class RevalidatedStaticFiles(StaticFiles):
        """The admin panel is ES modules imported by relative paths: without revalidation a browser keeps running an
        old page module after an update. no-cache still lets it reuse the file when the ETag has not changed."""

        def file_response(self, *args, **kwargs):
            response = super().file_response(*args, **kwargs)
            response.headers["Cache-Control"] = "no-cache"
            return response

        async def get_response(self, path, scope):
            # developer scripts (browser checks) live next to the pages but are not part of the product
            if path.replace("\\", "/").lstrip("/").startswith("scratch/"):
                from starlette.exceptions import HTTPException as StarletteHTTPException
                raise StarletteHTTPException(status_code=404)
            return await super().get_response(path, scope)

    static_dir = Path(__file__).resolve().parent.parent / "admin" / "static"
    if static_dir.exists():
        app.mount("/static", RevalidatedStaticFiles(directory=str(static_dir)), name="static")

    # Include routes
    app.include_router(health.router)
    app.include_router(inclusive_api.router)
    app.include_router(query.router)
    app.include_router(article.router)
    app.include_router(feedback.router)
    app.include_router(admin.router)
    app.include_router(editorial_router)
    app.include_router(webhooks.router)
    app.include_router(huquqplus_admin.router)
    app.include_router(corpus_admin.router)

    # Assistant & Gateway routers
    from src.gateway.router import router as assistant_router
    from src.gateway.openai_router import router as openai_router
    from src.gateway.admin_router import router as gateway_admin_router
    from src.gateway.review import admin_router as review_admin_router
    from src.gateway.review import router as review_router

    app.include_router(assistant_router)
    app.include_router(openai_router)
    app.include_router(gateway_admin_router)
    app.include_router(review_router)
    app.include_router(review_admin_router)

    return app


app = create_app()

