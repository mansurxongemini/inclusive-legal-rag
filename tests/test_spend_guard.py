"""OpenRouter budget guard: costs are summed per month, the state follows the budget, and the client pauses what it must."""

import httpx
import pytest

from src.clients.openrouter import OpenRouterClient
from src.clients.spend import SpendLedger, cost_of
from src.config import settings


def _ledger(tmp_path, scope="service"):
    return SpendLedger(path=str(tmp_path / "spend.db"), scope=scope)


def test_cost_comes_from_the_usage_object():
    assert cost_of({"cost": 1.5e-05, "prompt_tokens": 3}) == 1.5e-05
    assert cost_of({}) == 0.0 and cost_of(None) == 0.0 and cost_of({"cost": "x"}) == 0.0


def test_state_follows_the_monthly_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_MONTHLY_BUDGET_USD", 10.0)
    monkeypatch.setattr(settings, "OPENROUTER_BUDGET_SOFT_RATIO", 0.8)
    led = _ledger(tmp_path)
    assert led.state() == "ok"
    led.add("jev", 7.9)
    assert led.state() == "ok"
    led.add("chat", 0.2)
    assert led.state() == "soft"
    led.add("embedding", 2.0)
    assert led.state() == "exhausted"
    assert led.by_kind() == {"jev": 7.9, "chat": 0.2, "embedding": 2.0}
    monkeypatch.setattr(settings, "OPENROUTER_MONTHLY_BUDGET_USD", 0.0)
    assert led.state() == "ok"                       # 0 switches the guard off


def test_the_month_is_counted_from_the_file_and_evaluation_is_never_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_MONTHLY_BUDGET_USD", 1.0)
    led = _ledger(tmp_path)
    led.add("jev", 0.6)
    other_process = _ledger(tmp_path)               # a second process reads the same file
    assert other_process.month_total() == pytest.approx(0.6)
    assert _ledger(tmp_path / "x", scope="eval").state() == "ok"
    ev = _ledger(tmp_path / "y", scope="eval")
    ev.add("chat", 50.0)
    assert ev.state() == "ok"


class Exhausted:
    def __init__(self, state):
        self._state = state

    def state(self):
        return self._state

    def add(self, *a):
        self.added = a


def _client(handler):
    c = OpenRouterClient()
    c.is_mock = False
    c.api_key, c.base_url = "k", "https://openrouter.ai/api/v1"
    c._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


@pytest.mark.asyncio
async def test_optional_calls_leave_openrouter_once_the_soft_limit_is_reached(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "javob"}}], "usage": {"cost": 0.001}})

    c = _client(handler)
    fake = Exhausted("ok")
    monkeypatch.setattr("src.clients.openrouter.ledger", fake)
    assert await c.chat_completion([{"role": "user", "content": "q"}], min_chars=2, optional=True) == "javob"
    assert fake.added == ("chat", 0.001)
    monkeypatch.setattr("src.clients.openrouter.ledger", Exhausted("soft"))
    with pytest.raises(RuntimeError, match="optional"):
        await c.chat_completion([{"role": "user", "content": "q"}], min_chars=2, optional=True)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_embeddings_and_jev_pause_when_the_budget_is_used_up(monkeypatch):
    monkeypatch.setattr("src.clients.openrouter.ledger", Exhausted("exhausted"))
    c = _client(lambda r: httpx.Response(500))
    monkeypatch.setattr(OpenRouterClient, "embedding_is_mock", property(lambda self: False))
    with pytest.raises(RuntimeError, match="budget"):
        await c.get_embeddings(["savol"])
    assert await c.decide("state", {"q": {"type": "choice", "instructions": "x", "criteria": {"a": "b"}}}) is None


def test_a_provider_refusal_pauses_openrouter_calls_for_a_while(tmp_path, monkeypatch):
    from src.clients.spend import is_limit_error
    assert is_limit_error(403, '{"error":{"message":"Key limit exceeded (total limit)."}}')
    assert is_limit_error(402, "Payment required") and not is_limit_error(403, "forbidden") and not is_limit_error(500, "limit")
    led = _ledger(tmp_path)
    assert led.state() == "ok"
    led.trip("test")
    assert led.state() == "exhausted"
    led._tripped_until = 0.0
    led.provider_remaining = 0.0
    assert led.state() == "exhausted"                         # the key itself has nothing left
    led.provider_remaining = 0.5
    monkeypatch.setattr(settings, "OPENROUTER_MONTHLY_BUDGET_USD", 15.0)
    assert led.state() == "soft"                              # less than 20% of the budget is left on the key
    led.provider_remaining = 9.0
    assert led.state() == "ok"
