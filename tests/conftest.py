import pytest
from src.config import settings


@pytest.fixture(autouse=True)
def force_mock_for_tests(monkeypatch):
    """Enforce offline deterministic mock for automated pytest suite so tests run in ~4s and don't spend API tokens."""
    monkeypatch.setattr(settings, "MOCK_EXTERNAL_APIS", True)
