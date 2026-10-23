import json
import logging
import re
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from src.config import settings
from src.integrations.huquqplus_webhook import (
    MAX_BODY_BYTES,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    WebhookQueue,
    verify_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])

_queue: "WebhookQueue | None" = None


def get_webhook_queue() -> WebhookQueue:
    global _queue
    if _queue is None:
        _queue = WebhookQueue()
    return _queue


class HuquqPlusEvent(BaseModel):
    event: Literal["upsert", "delete", "ping"]
    event_id: str = Field(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    post_id: int = Field(..., ge=0, le=10**9)
    lang: str = Field(default="", max_length=8, pattern=r"^[a-z-]*$")
    modified_gmt: str = Field(default="", max_length=32)
    site: str = Field(default="", max_length=200)


@router.post("/huquqplus", status_code=202)
async def huquqplus_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives "post changed" notifications from the huquqplus.uz WordPress plugin. Authenticated by an HMAC
    signature (not by the admin key); the body never carries article text - the sync job re-fetches the post.
    """
    secret = settings.HUQUQPLUS_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook is not configured")

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")

    if not verify_signature(secret, request.headers.get(TIMESTAMP_HEADER), body, request.headers.get(SIGNATURE_HEADER)):
        logger.warning("Rejected huquqplus webhook with an invalid or expired signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = HuquqPlusEvent.model_validate(json.loads(body))
    except (ValueError, ValidationError):
        raise HTTPException(status_code=422, detail="Invalid payload")

    if payload.event == "ping":
        return {"status": "ok"}
    if payload.post_id <= 0:
        raise HTTPException(status_code=422, detail="post_id is required")

    lang = re.sub(r"[^a-z]", "", payload.lang) or "uz"
    queued = get_webhook_queue().enqueue(payload.event_id, payload.event, payload.post_id, lang, payload.modified_gmt)
    if queued:
        from src.integrations.huquqplus_sync import process_queue
        background_tasks.add_task(process_queue)
    return {"status": "queued" if queued else "duplicate"}
