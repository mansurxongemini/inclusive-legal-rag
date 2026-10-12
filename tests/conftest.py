import atexit
import os
import shutil
import tempfile

# The suite must never touch the real corpus, cache or API-key database in data/. Settings are read once at
# import time of src.config, so the environment has to be prepared before anything from src is imported.
_TEST_ROOT = tempfile.mkdtemp(prefix="legal_rag_tests_")
atexit.register(shutil.rmtree, _TEST_ROOT, ignore_errors=True)
os.environ["STORAGE_DIR"] = os.path.join(_TEST_ROOT, "store")
os.environ["CACHE_DB_PATH"] = os.path.join(_TEST_ROOT, "cache", "query_cache.db")
os.environ["REVIEW_QUEUE_PATH"] = os.path.join(_TEST_ROOT, "store", "review_queue.db")
os.environ["MOCK_EXTERNAL_APIS"] = "true"
os.environ["ADMIN_API_KEY"] = ""

import pytest
from src.config import settings


@pytest.fixture(scope="session", autouse=True)
def seeded_default_store():
    """The default (temporary) store holds the real, official text of O'RQ-641 so that app-level tests do not
    depend on test order. Mechanism tests that need statuses/cross-references use tests/fixtures instead."""
    import asyncio
    from pathlib import Path
    from src.clients.openrouter import OpenRouterClient
    from src.storage.hybrid_store import HybridStore

    store = HybridStore()
    if store.count() == 0:
        pilot = Path(__file__).resolve().parents[1] / "data" / "pilot_laws" / "law_disability_2020.json"
        client = OpenRouterClient()          # mock mode (MOCK_EXTERNAL_APIS=true above)
        asyncio.run(store.seed_from_file(str(pilot), client=client))
    yield


@pytest.fixture(autouse=True)
def force_mock_for_tests(monkeypatch):
    """Enforce offline deterministic mock for automated pytest suite so tests run in ~4s and don't spend API tokens."""
    monkeypatch.setattr(settings, "MOCK_EXTERNAL_APIS", True)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """The limiter is a process-wide singleton; keep one test's traffic from throttling the next."""
    from src.api.middleware.rate_limiter import rate_limiter
    rate_limiter.requests.clear()
    yield
    rate_limiter.requests.clear()
