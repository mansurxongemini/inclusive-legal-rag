"""
LLM routing: light helper calls run on a fast non-reasoning utility model, the Meta API gets `reasoning_effort`
(it rejects `reasoning`), and a failed generation model is backed up by a model on the other provider.
"""
import json

import httpx
import pytest

from src.clients.openrouter import OpenRouterClient, reasoning_fields
from src.config import settings

META = "https://api.meta.ai/v1"
OPENROUTER = "https://openrouter.ai/api/v1"
UTILITY = "https://openrouter.ai/api/v1"


def test_reasoning_fields_per_provider():
    assert reasoning_fields(OPENROUTER, {"enabled": False}) == {"reasoning": {"enabled": False}}
    assert reasoning_fields(OPENROUTER, {"effort": "low"}) == {"reasoning": {"effort": "low"}}
    assert reasoning_fields(META, {"enabled": False}) == {"reasoning_effort": "minimal"}
    assert reasoning_fields(META, {"effort": "HIGH"}) == {"reasoning_effort": "high"}
    assert reasoning_fields(META, {"effort": "none"}) == {}            # not a Meta level: leave the API default
    assert reasoning_fields(META, None) == {} and reasoning_fields(OPENROUTER, None) == {}
    assert reasoning_fields("https://other.example/v1", {"enabled": False}) == {}


def _reply(text):
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}


def _client(main_handler, utility_handler=None, monkeypatch=None):
    calls = {"main": [], "utility": []}

    def wrap(name, handler):
        def inner(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            calls[name].append(body)
            return handler(body)
        return httpx.AsyncClient(transport=httpx.MockTransport(inner))

    c = OpenRouterClient()
    c.is_mock = False
    c.base_url = META
    c.primary_model = c.fallback_model = "muse-spark-1.3"
    c._http_client = wrap("main", main_handler)
    if utility_handler is not None:
        c.utility_base_url, c.utility_api_key = UTILITY, "k"
        c._utility_http_client = wrap("utility", utility_handler)
    else:
        c.utility_api_key = None
    return c, calls


def ok(text):
    return lambda body: httpx.Response(200, json=_reply(text))


def fail(status=500):
    return lambda body: httpx.Response(status, json={"error": {"message": "boom"}})


MSG = [{"role": "user", "content": "savol"}]


@pytest.mark.asyncio
async def test_light_call_uses_the_utility_model_without_reasoning(monkeypatch):
    monkeypatch.setattr(settings, "UTILITY_MODEL", "fast/model")
    c, calls = _client(ok("main answer " * 5), ok("tarjima"))
    out = await c.chat_completion(MSG, min_chars=2, light=True, reasoning={"enabled": False})
    assert out == "tarjima"
    assert calls["main"] == [] and calls["utility"][0]["model"] == "fast/model"
    assert calls["utility"][0]["reasoning"] == {"enabled": False}      # OpenRouter-style endpoint


@pytest.mark.asyncio
async def test_light_call_falls_back_to_the_generation_model_with_minimal_reasoning(monkeypatch):
    monkeypatch.setattr(settings, "UTILITY_MODEL", "fast/model")
    c, calls = _client(ok("main answer " * 5), fail(500))
    out = await c.chat_completion(MSG, min_chars=2, light=True, reasoning={"enabled": False})
    assert out.startswith("main answer")
    assert calls["main"][0]["reasoning_effort"] == "minimal" and "reasoning" not in calls["main"][0]


@pytest.mark.asyncio
async def test_utility_endpoint_is_skipped_after_three_failures(monkeypatch):
    monkeypatch.setattr(settings, "UTILITY_MODEL", "fast/model")
    c, calls = _client(ok("main answer " * 5), fail(500))
    for _ in range(5):
        await c.chat_completion(MSG, min_chars=2, light=True)
    assert len(calls["utility"]) == 3 and len(calls["main"]) == 5      # breaker open for the last two calls


@pytest.mark.asyncio
async def test_generation_backup_answers_when_the_generation_model_is_down(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_MODEL_BACKUP", "backup/model")
    c, calls = _client(fail(500), ok("zaxira javobi " * 5))
    out = await c.chat_completion(MSG, reasoning={"enabled": False})
    assert out.startswith("zaxira javobi")
    assert calls["utility"][0]["model"] == "backup/model"
    assert len(calls["main"]) == 2                                      # one model name, two attempts (was four)


@pytest.mark.asyncio
async def test_rejected_request_is_not_retried_on_the_same_model():
    c, calls = _client(fail(400))
    with pytest.raises(RuntimeError):
        await c.chat_completion(MSG)
    assert len(calls["main"]) == 1


@pytest.mark.asyncio
async def test_no_backup_configured_still_raises(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_MODEL_BACKUP", "")
    c, _ = _client(fail(500), ok("x" * 60))
    with pytest.raises(RuntimeError):
        await c.chat_completion(MSG)


def _sse(*texts):
    def handler(body):
        lines = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}\n\n" for t in texts)
        return httpx.Response(200, text=lines + "data: [DONE]\n\n", headers={"content-type": "text/event-stream"})
    return handler


@pytest.mark.asyncio
async def test_stream_falls_over_to_the_backup_model_when_nothing_was_emitted(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_MODEL_BACKUP", "backup/model")
    c, calls = _client(_sse(), _sse("Zaxira ", "javob."))
    out = [t async for t in c.chat_completion_stream(MSG, max_tokens=2048, reasoning={"effort": "low"})]
    assert "".join(out) == "Zaxira javob."
    assert calls["main"][0]["reasoning_effort"] == "low" and calls["utility"][0]["model"] == "backup/model"


# --- second generation key ---------------------------------------------------------------------------------------------

def _two_key_client(statuses_by_key):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers["authorization"].split()[-1]
        seen.append(key)
        status = statuses_by_key[key]
        if status == 200:
            return httpx.Response(200, json=_reply("Javob matni " * 6))
        return httpx.Response(status, json={"error": {"code": "billing_not_configured"}})

    c = OpenRouterClient()
    c.is_mock = False
    c.base_url = META
    c.api_key, c._plus_api_key = "first", "second"
    c.primary_model = c.fallback_model = "muse-spark-1.3"
    c.utility_api_key = None
    c._http_client = None

    async def get_client():
        if c._http_client is None:
            c._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"Authorization": f"Bearer {c.api_key}"})
        return c._http_client

    c.get_client = get_client
    return c, seen


@pytest.mark.asyncio
async def test_a_402_from_the_first_key_switches_to_the_second_and_stays_there():
    c, seen = _two_key_client({"first": 402, "second": 200})
    assert (await c.chat_completion(MSG)).startswith("Javob matni")
    assert seen == ["first", "second"] and c.api_key == "second"
    await c.chat_completion(MSG)
    assert seen[-1] == "second" and seen.count("first") == 1


@pytest.mark.asyncio
async def test_both_keys_out_of_credit_is_an_error_not_a_loop():
    c, seen = _two_key_client({"first": 402, "second": 402})
    with pytest.raises(RuntimeError):
        await c.chat_completion(MSG)
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_stream_switches_key_on_402_too():
    seen = []

    def handler(request):
        key = request.headers["authorization"].split()[-1]
        seen.append(key)
        if key == "first":
            return httpx.Response(402, json={"error": {"code": "billing_not_configured"}})
        return _sse("Javob ", "matni.")(None)

    c = OpenRouterClient()
    c.is_mock = False
    c.base_url, c.api_key, c._plus_api_key = META, "first", "second"
    c.primary_model = c.fallback_model = "muse-spark-1.3"
    c.utility_api_key = None

    async def get_client():
        if c._http_client is None:
            c._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"Authorization": f"Bearer {c.api_key}"})
        return c._http_client

    c.get_client = get_client
    out = [t async for t in c.chat_completion_stream(MSG, max_tokens=2048)]
    assert "".join(out) == "Javob matni." and seen == ["first", "second"]
