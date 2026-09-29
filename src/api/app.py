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
from src.api.routes import query, article, feedback, health, admin

logger = logging.getLogger(__name__)

# Global instances
_store: Optional[HybridStore] = None
_cache: Optional[QueryCache] = None
_client: Optional[OpenRouterClient] = None


def get_store() -> HybridStore:
    global _store
    if _store is None:
        _store = HybridStore()
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
    store = get_store()
    client = get_client()

    if store.count() == 0:
        pilot_file = Path("data/pilot_laws/law_disability_2020.json")
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

    # Enable CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routes
    app.include_router(health.router)
    app.include_router(query.router)
    app.include_router(article.router)
    app.include_router(feedback.router)
    app.include_router(admin.router)

    return app


app = create_app()
