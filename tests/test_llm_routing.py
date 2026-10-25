"""
One OpenRouter key and endpoint serve every call, on one chat model: the cost of each reply is recorded, a budget that is
used up (or a key that is refused) stops the calls, and an optional helper call is skipped as soon as the budget runs low.
"""
import json

import httpx
import pytest

from src.clients.openrouter import OpenRouterClient, reasoning_fields
from src.clients.spend import SpendLedger
from src.config import settings

OPENROUTER = "https://openrouter.ai/api/v1"
MESSAGES = [{"role": "user", "content": "savol"}]


def test_reasoning_fields_are_for_openrouter_only():
    assert reasoning_fields(OPENROUTER, {"enabled": False}) == {"reasoning": {"enabled": False}}
    assert reasoning_fields(OPENROUTER, {"effort": "low"}) == {"reasoning": {"effort": "low"}}
    assert reasoning_fields(OPENROUTER, None) == {}
    assert reasoning_fields("https://other.example/v1", {"enabled": False}) == {}


def _reply(text, cost=None):
    body = {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
    if cost is not None:
        body["usage"] = {"cost": cost}
    return body


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    led = SpendLedger(path=str(tmp_path / "spend.db"), scope="service")
    monkeypatch.setattr("src.clients.openrouter.ledger", led)
    monkeypatch.setattr(settings, "OPENROUTER_MONTHLY_BUDGET_USD", 10.0)
    monkeypatch.setattr(settings, "OPENROUTER_BUDGET_SOFT_RATIO", 0.8)
    return led


def _client(handler):
    seen = []

    def inner(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return handler(len(seen))

    c = OpenRouterClient()
    c.is_mock = False
    c.api_key, c.base_url = "k", OPENROUTER
    c.primary_model = "vendor/chat-model"
    c._http_client = httpx.AsyncClient(transport=httpx.MockTransport(inner))
    return c, seen


def ok(text="Javob matni yetarlicha uzun bo'lishi kerak.", cost=0.001):
    return lambda n: httpx.Response(200, json=_reply(text, cost))


def sse(*chunks, usage=None):
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}\n\n" for t in chunks]
    if usage is not None:
        lines.append(f"data: {json.dumps({'choices': [], 'usage': usage})}\n\n")
    return httpx.Response(200, text="".join(lines) + "data: [DONE]\n\n", headers={"content-type": "text/event-stream"})


@pytest.mark.asyncio
async def test_one_model_answers_and_its_cost_is_recorded(ledger):
    c, seen = _client(ok(cost=0.0021))
    assert (await c.chat_completion(MESSAGES)).startswith("Javob matni")
    assert len(seen) == 1 and seen[0]["model"] == "vendor/chat-model"
    assert ledger.by_kind() == {"chat": 0.0021}


@pytest.mark.asyncio
async def test_a_helper_call_runs_without_reasoning(ledger):
    c, seen = _client(ok())
    await c.chat_completion(MESSAGES, light=True)
    assert seen[0]["reasoning"] == {"enabled": False}


@pytest.mark.asyncio
async def test_a_failed_call_is_asked_once_more_then_gives_up(ledger, monkeypatch):
    async def no_wait(_):
        return None

    monkeypatch.setattr("src.clients.openrouter.asyncio.sleep", no_wait)
    c, seen = _client(lambda n: httpx.Response(200, json=_reply("ok")) if n == 1 else httpx.Response(500, json={}))
    with pytest.raises(RuntimeError, match="did not answer"):
        await c.chat_completion(MESSAGES)                       # a stub reply, then a 500
    assert len(seen) == 2

    c, seen = _client(lambda n: httpx.Response(500, json={}) if n == 1 else httpx.Response(200, json=_reply("Javob matni yetarlicha uzun bo'lishi kerak.")))
    assert (await c.chat_completion(MESSAGES)).startswith("Javob")
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_a_request_the_provider_rejects_is_not_repeated(ledger):
    c, seen = _client(lambda n: httpx.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(RuntimeError):
        await c.chat_completion(MESSAGES)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_refused_key_stops_every_later_call(ledger):
    c, seen = _client(lambda n: httpx.Response(402, json={"error": {"code": "billing_not_configured"}}))
    with pytest.raises(RuntimeError, match="refused the key"):
        await c.chat_completion(MESSAGES)
    assert ledger.state() == "exhausted"
    with pytest.raises(RuntimeError, match="budget"):
        await c.chat_completion(MESSAGES)
    assert len(seen) == 1                                       # the second call never left the process


@pytest.mark.asyncio
async def test_optional_calls_stop_at_the_soft_limit_and_everything_stops_at_the_hard_one(ledger):
    c, seen = _client(ok())
    ledger.add("chat", 8.5)                                     # 85% of 10 USD
    assert ledger.state() == "soft"
    with pytest.raises(RuntimeError, match="optional"):
        await c.chat_completion(MESSAGES, light=True, optional=True)
    assert (await c.chat_completion(MESSAGES)).startswith("Javob")     # the answer itself still runs
    assert len(seen) == 1
    ledger.add("chat", 2.0)
    assert ledger.state() == "exhausted"
    with pytest.raises(RuntimeError, match="budget"):
        await c.chat_completion(MESSAGES)
    with pytest.raises(RuntimeError, match="budget"):
        async for _ in c.chat_completion_stream(MESSAGES):
            pass
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_paused_service_makes_no_call_at_all(ledger, monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_PAUSED", True)
    c, seen = _client(ok())
    with pytest.raises(RuntimeError, match="paused"):
        await c.chat_completion(MESSAGES)
    assert seen == []


@pytest.mark.asyncio
async def test_a_stream_records_its_cost_from_the_last_chunk(ledger):
    c, seen = _client(lambda n: sse("Javob ", "matni.", usage={"cost": 0.0042}))
    out = [t async for t in c.chat_completion_stream(MESSAGES)]
    assert "".join(out) == "Javob matni."
    assert seen[0]["stream"] is True and seen[0]["stream_options"] == {"include_usage": True}
    assert ledger.by_kind() == {"chat": 0.0042}


@pytest.mark.asyncio
async def test_a_stream_that_failed_before_its_first_token_is_asked_once_more(ledger, monkeypatch):
    async def no_wait(_):
        return None

    monkeypatch.setattr("src.clients.openrouter.asyncio.sleep", no_wait)
    c, seen = _client(lambda n: httpx.Response(503, json={}) if n == 1 else sse("Javob."))
    assert "".join([t async for t in c.chat_completion_stream(MESSAGES)]) == "Javob."
    assert len(seen) == 2


class _CutAfterFirstToken(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"choices": [{"delta": {"content": "Boshi"}}]}\n\n'
        raise httpx.ReadError("connection cut")

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_a_stream_cut_after_its_first_token_is_an_error_not_a_second_answer(ledger):
    c, seen = _client(lambda n: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=_CutAfterFirstToken()))
    got = []
    with pytest.raises(RuntimeError, match="interrupted"):
        async for t in c.chat_completion_stream(MESSAGES):
            got.append(t)
    assert got == ["Boshi"] and len(seen) == 1                  # no second attempt: it would splice two answers together


def test_openrouter_provider_routing_is_sent_only_to_openrouter(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER_ORDER", "deepinfra")
    monkeypatch.setattr(settings, "LLM_PROVIDER_QUANTIZATIONS", "fp8")
    c = OpenRouterClient()
    c.base_url = OPENROUTER
    assert c.provider_preferences() == {"order": ["deepinfra"], "allow_fallbacks": True, "quantizations": ["fp8"],
                                        "max_price": {"prompt": 0.10, "completion": 0.30}}
    c.base_url = "https://other.example/v1"
    assert c.provider_preferences() is None
