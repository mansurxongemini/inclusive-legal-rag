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
os.environ["MOCK_EXTERNAL_APIS"] = "true"
os.environ["ADMIN_API_KEY"] = ""

import pytest
from src.config import settings
# src.api resolves the attribute "app" lazily to the FastAPI object until the submodule src.api.app is imported, so a
# string patch such as monkeypatch.setattr("src.api.app.get_cache", ...) hit the FastAPI object whenever its test ran
# first. Importing the submodule here makes "src.api.app" mean the module in every order.
import src.api.app  # noqa: E402,F401


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
    # the Jev tests exercise Jev; the default of the product is JEV_ENABLED=False (see src/config.py)
    monkeypatch.setattr(settings, "JEV_ENABLED", True)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """The limiter is a process-wide singleton; keep one test's traffic from throttling the next."""
    from src.api.middleware.rate_limiter import rate_limiter
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """The suite is offline by contract (CI has no keys, and a test must never spend money or hit a live site). A socket
    that connects to anything but this machine is refused, and the test fails even when the code under test swallowed
    the error (a client that turns a connection failure into "provider unavailable" would hide it otherwise)."""
    import socket

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    attempts = []

    def _remote(address) -> bool:
        if not isinstance(address, tuple):
            return False                                          # unix socket
        host = address[0]
        return not (isinstance(host, str) and (host in ("localhost", "::1") or host.startswith("127.")))

    def guarded_connect(self, address):
        if _remote(address):
            attempts.append(address)
            raise OSError(f"a test tried to open a real network connection to {address!r}")
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        if _remote(address):
            attempts.append(address)
            raise OSError(f"a test tried to open a real network connection to {address!r}")
        return real_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    yield
    assert not attempts, f"the test reached the network: {attempts}"
