import os
import psutil
from fastapi import APIRouter, Depends
from src.storage.hybrid_store import HybridStore
from src.config import settings

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


@router.get("/health")
async def health_check():
    rss_mb = get_process_memory_mb()
    
    # Check storage health
    store_healthy = True
    article_count = 0
    try:
        from src.api.app import get_store
        store = get_store()
        article_count = store.count()
    except Exception:
        store_healthy = False

    return {
        "status": "healthy" if store_healthy else "degraded",
        "service": "uzbekistan-legal-rag",
        "version": "1.0.0",
        "mock_mode": settings.is_mock_mode,
        "rss_memory_mb": rss_mb,
        "memory_budget_exceeded": (rss_mb > 350.0),
        "articles_indexed": article_count,
    }
