"""
Streaming answers from an always-reasoning model: the reasoning shares max_tokens, so a too small budget used to end
the stream before any answer text and the site showed only the disclaimer and a "source check failed" note.
"""
import json

import httpx
import pytest

from src.clients.openrouter import REASONING_MODEL_MIN_TOKENS, OpenRouterClient, output_token_budget


def _client(lines_for_request):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        text = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in lines_for_request(body)) + "data: [DONE]\n\n"
        return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})

    c = OpenRouterClient()
    c.is_mock = False
    c.primary_model = c.fallback_model = "muse-spark-1.3"
    c.utility_api_key = None                      # no backup model: these tests never leave the mock transport
    c._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c, seen


def _chunk(content=None, finish=None):
    delta = {"content": content} if content is not None else {}
    return {"choices": [{"delta": delta, "finish_reason": finish, "index": 0}]}


def test_reasoning_models_get_room_for_their_reasoning():
    assert output_token_budget("muse-spark-1.3", 2048) == REASONING_MODEL_MIN_TOKENS
    assert output_token_budget("muse-spark-1.3", 16000) == 16000
    assert output_token_budget("meta-llama/llama-3.3-70b-instruct", 2048) == 2048


@pytest.mark.asyncio
async def test_stream_asks_for_the_reasoning_budget_and_yields_the_answer():
    client, seen = _client(lambda body: [_chunk("Javob "), _chunk("matni."), _chunk(finish="stop")])
    out = [t async for t in client.chat_completion_stream([{"role": "user", "content": "savol"}], max_tokens=2048)]
    assert "".join(out) == "Javob matni."
    assert seen[0]["max_tokens"] == REASONING_MODEL_MIN_TOKENS


@pytest.mark.asyncio
async def test_stream_without_answer_text_is_an_error_not_an_empty_answer():
    client, seen = _client(lambda body: [_chunk(finish="stop")])     # reasoning used the whole budget
    with pytest.raises(RuntimeError, match="empty stream"):
        _ = [t async for t in client.chat_completion_stream([{"role": "user", "content": "savol"}], max_tokens=2048)]
    assert len(seen) == 1                                              # same model as fallback: tried once
