import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.storage.hybrid_store import HybridStore
from src.api.cache import QueryCache
from src.clients.openrouter import OpenRouterClient
from src.api.routes import query, article, feedback, health, admin, inclusive_api

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure directories & seed pilot dataset if empty
    settings.ensure_directories()
    if settings.is_mock_mode and not settings.MOCK_EXTERNAL_APIS:
        logger.warning(
            "OPENROUTER_API_KEY is not set: running in MOCK mode. Answers are deterministic placeholders, "
            "not real legal analysis. Configure the key (or set MOCK_EXTERNAL_APIS=true to silence this)."
        )
    store = get_store()
    client = get_client()

    if store.count() == 0:
        pilot_file = _PROJECT_ROOT / "data" / "pilot_laws" / "law_disability_2020.json"
        if pilot_file.exists():
            logger.info("Initializing knowledge base with pilot disability rights law...")
            await store.seed_from_file(str(pilot_file), client=client)

    yield

    # Shutdown
    if _client:
        await _client.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Uzbekistan Legal RAG API",
        description="Production-grade, ultra-accurate Multilingual Legal RAG Platform for Uzbekistan Legislation",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Enable CORS (no cookies are used, so credentialed cross-origin requests are not needed)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files for admin panel
    from fastapi.staticfiles import StaticFiles
    static_dir = Path(__file__).resolve().parent.parent / "admin" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Include routes
    app.include_router(health.router)
    app.include_router(inclusive_api.router)
    app.include_router(query.router)
    app.include_router(article.router)
    app.include_router(feedback.router)
    app.include_router(admin.router)

    return app


app = create_app()
