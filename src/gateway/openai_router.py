"""
OpenAI-compatible chat completions and models endpoints.
Prefix: /api/v1/openai
"""
import json
import logging
import secrets
import time
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from src.gateway.auth import (
    ClientContext,
    enforce_daily_quota,
    enforce_user_limit,
    require_scope,
)
from src.api.middleware.security import sanitize_user_input
from src.gateway.clients import get_client_store, user_ref
from src.gateway.conversations import get_conversation_store
from src.gateway.formatting import format_citations
from src.generation.validator import CitationItem
from src.gateway.service import (
    AnswerResult,
    answer_question,
    condense_question,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/openai", tags=["OpenAI Compatible API"])

MODEL_ID = "huquqplus-assistant"


MAX_QUESTION_CHARS = 4000
MAX_HISTORY_CHARS = 2000          # per earlier message; only used to rewrite a follow-up question
GENERIC_ERROR = "Ichki xatolik yuz berdi. Birozdan so'ng qayta urining."


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    # a string, or OpenAI content parts [{"type": "text", "text": "..."}, ...]
    content: Union[str, List[dict], None] = None
    name: Optional[str] = None

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return "\n".join(str(p.get("text", "")) for p in self.content
                             if isinstance(p, dict) and p.get("type") in ("text", "input_text"))
        return ""


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messages: List[ChatMessage] = Field(..., min_length=1, max_length=50)
    model: Optional[str] = Field(default=MODEL_ID)
    stream: bool = Field(default=False)
    user: Optional[str] = Field(default=None, max_length=256)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None



def _sources_block(structured_cits: List[dict]) -> str:
    """'Manbalar:' list appended to the answer text (tools that show only the text still show the sources)."""
    if not structured_cits:
        return ""
    lines = ["", "", "Manbalar:"]
    for c in structured_cits:
        label = " ".join(x for x in (c.get("law_number"), c.get("article")) if x) or c.get("title", "")
        lines.append(f"{c['number']}. {label}: {c['url']}" if c.get("url") else f"{c['number']}. {label}")
    return "\n".join(lines)


def _openai_error(status: int, message: str, code: str, error_type: str = "invalid_request_error") -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error": {"message": message, "type": error_type, "code": code}},
    )


def _safe_text(text: str) -> str:
    """Prompt-injection check in the OpenAI error shape; applied to the question and to every history message."""
    try:
        return sanitize_user_input(text)
    except HTTPException as e:
        message = e.detail if isinstance(e.detail, str) else "Xavfsizlik qoidalariga zid so'rov aniqlandi."
        raise _openai_error(400, message, "unsafe_input")


@router.get("/models")
async def list_models(ctx: ClientContext = Depends(require_scope("ask"))):
    """Lists available models in OpenAI format."""
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": 1700000000,
                "owned_by": "huquqplus",
            }
        ],
    }


@router.post("/chat/completions")
async def chat_completions(
    payload: ChatCompletionRequest,
    ctx: ClientContext = Depends(require_scope("ask")),
):
    """
    OpenAI-compatible /chat/completions endpoint.
    - System messages are IGNORED (clients cannot override our prompt).
    - Last user message is the question.
    - Earlier user/assistant messages are history for condensation.
    - 'user' field maps to user_id.
    """
    from src.api.app import get_client

    # Only the conversation itself counts: system/developer/tool messages are ignored, so a client cannot
    # replace our instructions
    filtered = [m for m in payload.messages if m.role in ("user", "assistant")]
    if not filtered:
        raise _openai_error(400, "kamida bitta 'user' xabari kerak.", "invalid_messages")

    # Find last user message
    user_indices = [i for i, m in enumerate(filtered) if m.role == "user"]
    if not user_indices:
        raise _openai_error(400, "kamida bitta 'user' xabari kerak.", "missing_user_message")

    last_user_idx = user_indices[-1]
    last_user_msg = filtered[last_user_idx]
    question = last_user_msg.text().strip()

    if not question:
        raise _openai_error(400, "Savol matni bo'sh bo'lishi mumkin emas.", "empty_question")
    if len(question) > MAX_QUESTION_CHARS:
        raise _openai_error(400, f"Savol {MAX_QUESTION_CHARS} belgidan oshmasligi kerak.", "question_too_long")

    # Earlier messages are history (last few, truncated). The injection check covers them too and runs before
    # quota use and before any LLM call (condensation reads the history).
    question = _safe_text(question)
    if not question:
        raise _openai_error(400, "Savol matni bo'sh bo'lishi mumkin emas.", "empty_question")
    history = [{"role": m.role, "content": _safe_text(m.text()[:MAX_HISTORY_CHARS])} for m in filtered[:last_user_idx]][-8:]

    # User ref & limits
    ref = user_ref(ctx.client.client_id, payload.user)
    enforce_user_limit(ctx, ref)
    enforce_daily_quota(ctx)

    # Condensation
    client_llm = get_client()
    standalone_q = await condense_question(history, question, client=client_llm)

    completion_id = f"chatcmpl-{secrets.token_hex(12)}"
    created_time = int(time.time())

    # Streaming mode
    if payload.stream:
        return _handle_streaming_chat(
            ctx=ctx,
            completion_id=completion_id,
            created_time=created_time,
            standalone_q=standalone_q,
            question=question,
            ref=ref,
        )

    # Non-streaming mode
    t0 = time.time()
    try:
        result: AnswerResult = await answer_question(standalone_q)
    except HTTPException as e:
        get_client_store().record_outcome(ctx.client.client_id, error=True)
        message = e.detail if isinstance(e.detail, str) else GENERIC_ERROR
        raise _openai_error(e.status_code, message, "service_unavailable" if e.status_code == 503 else "api_error",
                            "api_error")
    except Exception:
        logger.exception("openai-compatible completion failed")
        get_client_store().record_outcome(ctx.client.client_id, error=True)
        raise _openai_error(500, GENERIC_ERROR, "server_error", "api_error")

    get_client_store().record_outcome(ctx.client.client_id, refusal=result.is_refusal, error=False)

    structured_cits = [c.to_dict() for c in format_citations(result.citations)]
    get_conversation_store().record_answer(
        client_id=ctx.client.client_id, user_ref=ref, conversation_id=None, question=question,
        answer=result.clean_answer or result.answer, citations_json=json.dumps(structured_cits, ensure_ascii=False),
        is_refusal=result.is_refusal, latency_ms=int((time.time() - t0) * 1000), answer_id=completion_id,
    )

    content = (result.clean_answer or result.answer) + _sources_block(structured_cits)

    q_tokens = max(1, len(question.split()))
    a_tokens = max(1, len(content.split()))

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created_time,
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": q_tokens,
            "completion_tokens": a_tokens,
            "total_tokens": q_tokens + a_tokens,
        },
        "citations": structured_cits,
    }


def _handle_streaming_chat(
    ctx: ClientContext,
    completion_id: str,
    created_time: int,
    standalone_q: str,
    question: str,
    ref: Optional[str],
) -> StreamingResponse:
    from src.gateway.service import answer_question_stream_events

    async def _stream_generator():
        t0 = time.time()
        tokens: List[str] = []
        final_event: dict = {}
        # Initial chunk with role
        initial_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(initial_chunk)}\n\n"

        try:
            async for ev in answer_question_stream_events(standalone_q):
                ev_type = ev.get("type")
                if ev_type == "token":
                    delta_text = ev.get("text", "")
                    tokens.append(delta_text)
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": MODEL_ID,
                        "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
                elif ev_type == "done":
                    final_event = ev
                elif ev_type == "error":
                    get_client_store().record_outcome(ctx.client.client_id, error=True)
                    err_chunk = {
                        "error": {
                            "message": "Javob yaratish xizmati vaqtincha mavjud emas.",
                            "type": "api_error",
                            "code": "generation_error",
                        }
                    }
                    yield f"data: {json.dumps(err_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
        except Exception:
            logger.exception("openai-compatible stream failed")
            get_client_store().record_outcome(ctx.client.client_id, error=True)
            err_chunk = {"error": {"message": GENERIC_ERROR, "type": "api_error", "code": "server_error"}}
            yield f"data: {json.dumps(err_chunk)}\n\n"
            yield "data: [DONE]\n\n"
            return

        sources = _sources_block([c.to_dict() for c in format_citations(
            [CitationItem(**c) for c in (final_event.get("citations") or []) if isinstance(c, dict)])])
        if sources:
            chunk = {
                "id": completion_id, "object": "chat.completion.chunk", "created": created_time, "model": MODEL_ID,
                "choices": [{"index": 0, "delta": {"content": sources}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        is_refusal = bool(final_event.get("is_refusal", False))
        get_client_store().record_outcome(ctx.client.client_id, refusal=is_refusal, error=False)
        get_conversation_store().record_answer(
            client_id=ctx.client.client_id, user_ref=ref, conversation_id=None, question=question,
            answer=final_event.get("clean_answer") or "".join(tokens),
            citations_json=json.dumps(final_event.get("citations") or [], ensure_ascii=False),
            is_refusal=is_refusal, latency_ms=int((time.time() - t0) * 1000), answer_id=completion_id,
        )

        # Final chunk
        final_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_stream_generator(), media_type="text/event-stream")
