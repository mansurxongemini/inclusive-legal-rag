"""
Assistant API router for external clients (Telegram bot, websites, partner services).
Prefix: /api/v1/assistant
"""
import json
import logging
import secrets
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.domain.disability_taxonomy import CATEGORY_IDS, DISABILITY_GROUPS
from src.gateway.auth import (
    ClientContext,
    authenticate_client,
    enforce_daily_quota,
    enforce_user_limit,
    gateway_error,
    require_scope,
)
from src.gateway.clients import get_client_store, user_ref
from src.gateway.conversations import get_conversation_store
from src.generation.prompts import disclaimer_text
from src.gateway.formatting import (
    format_citations,
    split_parts,
    telegram_sources_block,
    to_plain_text,
    to_telegram_html,
)
from src.gateway.service import (
    AnswerResult,
    answer_question,
    condense_question,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/assistant", tags=["Assistant API"])

DISCLAIMER_TEXT = disclaimer_text("uz")  # kept for importers; responses use disclaimer_text(<answer language>)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000, description="Legal question")
    user_id: Optional[str] = Field(default=None, max_length=256, description="Client's own end-user id")
    conversation_id: Optional[str] = Field(default=None, max_length=128, description="Existing conversation id")
    language: Literal["auto", "uz", "ru", "en"] = Field(default="auto")
    format: Literal["markdown", "text", "telegram_html"] = Field(default="markdown")
    mode: Literal["plain", "legal_text", "easy_read", "subsumption"] = Field(default="plain")
    disability_group: str = Field(default="all")
    category: str = Field(default="all")
    stream: bool = Field(default=False)

    @field_validator("disability_group")
    @classmethod
    def _check_group(cls, v: str) -> str:
        allowed = {"all", "general", *(g.id for g in DISABILITY_GROUPS)}
        if v not in allowed:
            raise ValueError(f"disability_group must be one of {sorted(allowed)}")
        return v

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        if v != "all" and v not in CATEGORY_IDS:
            raise ValueError(f"category must be 'all' or one of {CATEGORY_IDS}")
        return v


class FeedbackPayload(BaseModel):
    answer_id: str = Field(..., min_length=1, max_length=128)
    rating: Literal["up", "down"]
    comment: Optional[str] = Field(default="", max_length=2000)


class ConversationDeletePayload(BaseModel):
    user_id: Optional[str] = Field(default=None, max_length=256)


def _format_answer_text(raw_markdown: str, fmt: str) -> str:
    if fmt == "text":
        return to_plain_text(raw_markdown)
    elif fmt == "telegram_html":
        return to_telegram_html(raw_markdown)
    return raw_markdown


def _with_sources(formatted_answer: str, citations, language: str) -> str:
    import html as _html
    import re as _re
    from src.gateway.formatting import is_well_formed_telegram_html

    body = formatted_answer
    url_map = {
        c.number: _html.escape(c.url, quote=True)
        for c in (citations or [])
        if getattr(c, "url", None) and c.url.startswith(("https://", "http://"))
    }
    if url_map:
        # Link inline [n] markers that are not already inside an <a>...</a> tag
        parts = _re.split(r"(<a\s[^>]*>.*?</a>)", body, flags=_re.DOTALL | _re.IGNORECASE)
        for idx in range(0, len(parts), 2):
            def _sub_cit(m):
                num = int(m.group(1))
                u = url_map.get(num)
                return f'<a href="{u}">[{num}]</a>' if u else m.group(0)
            parts[idx] = _re.sub(r"\[(\d{1,2})\]", _sub_cit, parts[idx])
        candidate = "".join(parts)
        if is_well_formed_telegram_html(candidate):
            body = candidate

    sources = telegram_sources_block(citations, language)
    return f"{body}\n\n{sources}" if sources else body


@router.post("/ask")
async def ask_assistant(
    payload: AskRequest,
    ctx: ClientContext = Depends(require_scope("ask")),
):
    """
    Asks the legal assistant:
    1. require_scope("ask")
    2. sanitize input (empty -> 422)
    3. ref = user_ref(client_id, user_id)
    4. enforce_user_limit
    5. conversation ownership (404 if invalid)
    6. enforce_daily_quota
    7. condense question
    8. answer (non-stream or SSE)
    9. format
    10. store answer + turn
    11. record outcome
    12. return response
    """
    from src.api.middleware.security import sanitize_user_input
    from src.api.app import get_client

    # 2. Sanitize
    cleaned_query = sanitize_user_input(payload.question)
    if not cleaned_query:
        raise gateway_error(422, "invalid_request", "Savol matni bo'sh bo'lishi mumkin emas.")

    # 3. User ref
    ref = user_ref(ctx.client.client_id, payload.user_id)

    # 4. Enforce per-user limit
    enforce_user_limit(ctx, ref)

    # 5. Conversation ownership (an existing id must belong to this client and user)
    conv_store = get_conversation_store()
    if payload.conversation_id:
        conv, _ = conv_store.get_or_create_conversation(payload.conversation_id, ctx.client.client_id, ref)
        if conv is None:
            raise gateway_error(404, "conversation_not_found", "Suhbat topilmadi yoki unga kirish ruxsati yo'q.")

    # 6. Enforce daily quota (before anything is created for this request)
    enforce_daily_quota(ctx)
    if not payload.conversation_id:
        conv, _ = conv_store.get_or_create_conversation(None, ctx.client.client_id, ref)
    conversation_id = conv.conversation_id

    # 7. Condense question
    history = conv_store.get_history(conversation_id, max_turns=4)
    client_llm = get_client()
    standalone_q = await condense_question(history, cleaned_query, client=client_llm)

    # 8. Streaming mode
    if payload.stream:
        return _handle_streaming_ask(
            ctx=ctx,
            payload=payload,
            cleaned_query=cleaned_query,
            standalone_q=standalone_q,
            conversation_id=conversation_id,
            user_ref_val=ref,
        )

    # 8-12. Non-streaming mode
    t0 = time.time()
    try:
        result: AnswerResult = await answer_question(
            standalone_q,
            language=payload.language,
            mode=payload.mode,
            disability_group=payload.disability_group,
            category=payload.category,
        )
    except HTTPException:
        get_client_store().record_outcome(ctx.client.client_id, error=True)
        raise
    except Exception:
        logger.exception("assistant ask failed")
        get_client_store().record_outcome(ctx.client.client_id, error=True)
        raise gateway_error(500, "server_error", "Ichki xatolik yuz berdi. Birozdan so'ng qayta urining.")

    latency_ms = int((time.time() - t0) * 1000)

    # 9. Format
    raw_markdown = result.clean_answer or result.answer
    formatted_answer = _format_answer_text(raw_markdown, payload.format)
    citation_objs = format_citations(result.citations)
    if payload.format == "telegram_html":
        formatted_answer = _with_sources(formatted_answer, citation_objs, result.detected_language)
    parts = split_parts(formatted_answer, limit=4096)
    structured_cits = [c.to_dict() for c in citation_objs]

    # 10. Store answer + turn (markdown: the history and the review queue must not depend on the client format)
    stored_ans = conv_store.record_answer(
        client_id=ctx.client.client_id,
        user_ref=ref,
        conversation_id=conversation_id,
        question=cleaned_query,
        answer=raw_markdown,
        citations_json=json.dumps(structured_cits, ensure_ascii=False),
        is_refusal=result.is_refusal,
        latency_ms=latency_ms,
    )
    citation_ids = [c.canonical_id for c in result.citations]
    conv_store.add_turn(
        conversation_id=conversation_id,
        question=cleaned_query,
        standalone_question=standalone_q,
        answer=raw_markdown,
        citation_ids=citation_ids,
    )

    # 11. Record outcome
    get_client_store().record_outcome(ctx.client.client_id, refusal=result.is_refusal, error=False)

    # 12. Response
    return {
        "answer_id": stored_ans.answer_id,
        "conversation_id": conversation_id,
        "answer": formatted_answer,
        "format": payload.format,
        "parts": parts,
        "citations": structured_cits,
        "is_refusal": result.is_refusal,
        "validation_passed": result.validation_passed,
        "language": result.detected_language,
        "standalone_question": standalone_q,
        "disclaimer": disclaimer_text(result.detected_language),
        "latency_ms": latency_ms,
        "cached": result.cached,
    }


def _handle_streaming_ask(
    ctx: ClientContext,
    payload: AskRequest,
    cleaned_query: str,
    standalone_q: str,
    conversation_id: str,
    user_ref_val: Optional[str],
) -> StreamingResponse:
    """Handles SSE streaming for /api/v1/assistant/ask."""
    from src.gateway.service import answer_question_stream_events
    from src.generation.validator import CitationItem

    answer_id = secrets.token_urlsafe(16)
    conv_store = get_conversation_store()

    async def _stream_generator():
        t0 = time.time()
        # 1. Event: meta
        yield f"event: meta\ndata: {json.dumps({'answer_id': answer_id, 'conversation_id': conversation_id})}\n\n"

        tokens_accumulated = []
        final_event = None

        try:
            async for ev in answer_question_stream_events(
                standalone_q,
                language=payload.language,
                mode=payload.mode,
                disability_group=payload.disability_group,
                category=payload.category,
            ):
                ev_type = ev.get("type")
                if ev_type == "token":
                    chunk_text = ev.get("text", "")
                    tokens_accumulated.append(chunk_text)
                    yield f"event: delta\ndata: {json.dumps({'text': chunk_text})}\n\n"
                elif ev_type == "done":
                    final_event = ev
                elif ev_type == "error":
                    get_client_store().record_outcome(ctx.client.client_id, error=True)
                    message = "Javob yaratish xizmati vaqtincha mavjud emas. Birozdan so'ng qayta urining."
                    yield f"event: error\ndata: {json.dumps({'code': 'generation_error', 'message': message})}\n\n"
                    return
        except Exception:
            logger.exception("assistant stream failed")
            get_client_store().record_outcome(ctx.client.client_id, error=True)
            message = "Ichki xatolik yuz berdi. Birozdan so'ng qayta urining."
            yield f"event: error\ndata: {json.dumps({'code': 'server_error', 'message': message})}\n\n"
            return

        latency_ms = int((time.time() - t0) * 1000)

        # Build final response object
        raw_answer = "".join(tokens_accumulated)
        if final_event and final_event.get("clean_answer"):
            raw_answer = final_event.get("clean_answer")

        cits_raw = (final_event.get("citations") if final_event else []) or []
        citation_items = [CitationItem(**c) if isinstance(c, dict) else c for c in cits_raw]
        citation_objs = format_citations(citation_items)
        structured_cits = [c.to_dict() for c in citation_objs]
        is_refusal = bool(final_event.get("is_refusal", False)) if final_event else False
        detected_lang = (final_event.get("language") if final_event else None) or "uz"

        formatted_answer = _format_answer_text(raw_answer, payload.format)
        if payload.format == "telegram_html":
            formatted_answer = _with_sources(formatted_answer, citation_objs, detected_lang)
        parts = split_parts(formatted_answer, limit=4096)

        # Store answer + turn (markdown)
        conv_store.record_answer(
            client_id=ctx.client.client_id, user_ref=user_ref_val, conversation_id=conversation_id,
            question=cleaned_query, answer=raw_answer,
            citations_json=json.dumps(structured_cits, ensure_ascii=False),
            is_refusal=is_refusal, latency_ms=latency_ms, answer_id=answer_id,
        )
        conv_store.add_turn(
            conversation_id=conversation_id, question=cleaned_query, standalone_question=standalone_q,
            answer=raw_answer, citation_ids=[c.canonical_id for c in citation_items],
        )

        get_client_store().record_outcome(ctx.client.client_id, refusal=is_refusal, error=False)

        done_payload = {
            "answer_id": answer_id,
            "conversation_id": conversation_id,
            "answer": formatted_answer,
            "format": payload.format,
            "parts": parts,
            "citations": structured_cits,
            "is_refusal": is_refusal,
            "validation_passed": bool(final_event.get("validation_passed", False)) if final_event else False,
            "language": detected_lang,
            "standalone_question": standalone_q,
            "disclaimer": disclaimer_text(detected_lang),
            "latency_ms": latency_ms,
            "cached": False,
        }
        yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(_stream_generator(), media_type="text/event-stream")


@router.post("/feedback")
async def submit_feedback(
    payload: FeedbackPayload,
    ctx: ClientContext = Depends(require_scope("feedback")),
):
    """
    Submits feedback for an answer:
    - require_scope("feedback")
    - answer must belong to the calling client (else 404)
    - forwards to store.fts_store.record_feedback (up=5, down=1)
    """
    conv_store = get_conversation_store()
    stored = conv_store.get_answer(payload.answer_id)
    if stored is None or stored.client_id != ctx.client.client_id:
        raise gateway_error(404, "answer_not_found", "Javob topilmadi yoki boshqa mijozga tegishli.")

    conv_store.record_feedback(payload.answer_id, payload.rating, payload.comment or "")

    # Forward to fts_store for the evaluation set
    from src.api.app import get_store
    app_store = get_store()
    rating_num = 5 if payload.rating == "up" else 1

    try:
        cits = json.loads(stored.citations_json)
        canonical_ids = [c["canonical_id"] for c in cits if isinstance(c, dict) and c.get("canonical_id")]
    except Exception:
        canonical_ids = []

    app_store.fts_store.record_feedback(
        query=stored.question,
        answer=stored.answer,
        canonical_ids=canonical_ids,
        rating=rating_num,
        feedback_text=payload.comment or "",
    )

    return {"status": "success", "message": "Fikr-mulohazangiz qabul qilindi. Rahmat!"}


@router.get("/me")
async def get_me(ctx: ClientContext = Depends(authenticate_client)):
    """Returns client name, kind, scopes, limits, requests today (never key material)."""
    return {
        "client_id": ctx.client.client_id,
        "name": ctx.client.name,
        "kind": ctx.client.kind,
        "scopes": ctx.client.scopes,
        "limits": {
            "rate_per_min": ctx.client.rate_per_min,
            "user_rate_per_min": ctx.client.user_rate_per_min,
            "daily_quota": ctx.client.daily_quota,
        },
        "requests_today": get_client_store().usage_today(ctx.client.client_id),
    }


@router.post("/conversations/{conversation_id}/delete")
async def delete_conversation(
    conversation_id: str,
    payload: Optional[ConversationDeletePayload] = None,
    ctx: ClientContext = Depends(require_scope("ask")),
):
    """Deletes that user's conversation and its turns."""
    u_id = payload.user_id if payload else None
    ref = user_ref(ctx.client.client_id, u_id)
    conv_store = get_conversation_store()
    deleted = conv_store.delete_conversation(conversation_id, ctx.client.client_id, ref)
    if not deleted:
        raise gateway_error(404, "conversation_not_found", "Suhbat topilmadi yoki unga kirish huquqi yo'q.")
    return {"deleted": True, "conversation_id": conversation_id}
