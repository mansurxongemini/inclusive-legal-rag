import os
import psutil
from fastapi import APIRouter, Depends
from src.api.auth.admin import require_admin
from src.config import settings
from src.clients.spend import ledger

router = APIRouter(tags=["Health"])


def get_process_memory_mb() -> float:
    try:
        process = psutil.Process(os.getpid())
        return round(process.memory_info().rss / (1024 * 1024), 2)
    except Exception:
        # Fallback via /proc/self/status on Linux
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return round(int(line.split()[1]) / 1024.0, 2)
        except Exception:
            pass
        return 0.0


def _snapshot() -> dict:
    """The service's state: store reachable, budget state, memory. Plain `def` (it reads SQLite): runs in the thread pool."""
    store_healthy = True
    article_count = 0
    try:
        from src.api.app import get_store
        article_count = get_store().count()
    except Exception:
        store_healthy = False

    budget_state = ledger.state()
    rss_mb = get_process_memory_mb()
    return {
        "status": "healthy" if store_healthy and budget_state != "exhausted" else "degraded",
        # ok | soft (light calls on the free provider) | exhausted (embeddings and Jev paused: full-text search only)
        "openrouter_budget": budget_state,
        "service": "uzbekistan-legal-rag",
        "version": "1.0.0",
        "mock_mode": settings.is_mock_mode,
        "rss_memory_mb": rss_mb,
        "memory_budget_mb": settings.MEMORY_BUDGET_MB,
        "memory_budget_exceeded": (rss_mb > settings.MEMORY_BUDGET_MB),
        "articles_indexed": article_count,
        "spend": ledger.summary(),
    }


@router.get("/health")
def health_check():
    """Public liveness for load balancers and the container health check: the status and nothing about the internals."""
    snap = _snapshot()
    return {"status": snap["status"], "service": snap["service"], "version": snap["version"]}


@router.get("/health/details", dependencies=[Depends(require_admin)])
def health_details():
    """Budget state, memory and corpus size: administrators only (the public /health does not publish them)."""
    return _snapshot()
