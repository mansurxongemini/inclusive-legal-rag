"""Administration of integration clients and their keys (administrators only)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth.admin import require_admin
from src.gateway.clients import KINDS, SCOPES, get_client_store

router = APIRouter(prefix="/api/v1/admin/integrations", tags=["Integrations (admin)"],
                   dependencies=[Depends(require_admin)])


class ClientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    kind: str = Field(default="server", description=f"one of {KINDS}")
    scopes: List[str] = Field(default_factory=lambda: list(SCOPES))
    allowed_origins: List[str] = Field(default_factory=list, max_length=20)
    rate_per_min: int = Field(default=120, ge=1, le=10000)
    user_rate_per_min: int = Field(default=10, ge=1, le=1000)
    daily_quota: int = Field(default=0, ge=0, description="0 = unlimited")
    note: str = Field(default="", max_length=500)


class ClientUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    scopes: Optional[List[str]] = None
    allowed_origins: Optional[List[str]] = Field(default=None, max_length=20)
    rate_per_min: Optional[int] = Field(default=None, ge=1, le=10000)
    user_rate_per_min: Optional[int] = Field(default=None, ge=1, le=1000)
    daily_quota: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=500)


class KeyCreate(BaseModel):
    expires_at: Optional[float] = Field(default=None, description="unix time; empty = no expiry")


def _client_or_404(client_id: str):
    client = get_client_store().get_client(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi.")
    return client


@router.get("/clients")
async def list_clients():
    store = get_client_store()
    out = []
    for c in store.list_clients():
        keys = store.list_keys(c.client_id)
        out.append({**c.to_dict(), "active_keys": sum(1 for k in keys if k.is_usable),
                    "requests_today": store.usage_today(c.client_id)})
    return {"clients": out, "kinds": list(KINDS), "scopes": list(SCOPES)}


@router.post("/clients", status_code=201)
async def create_client(payload: ClientCreate):
    """Creates a client and its first key. The key is returned only in this response."""
    store = get_client_store()
    try:
        client = store.create_client(payload.name, kind=payload.kind, scopes=payload.scopes,
                                     allowed_origins=payload.allowed_origins, rate_per_min=payload.rate_per_min,
                                     user_rate_per_min=payload.user_rate_per_min, daily_quota=payload.daily_quota,
                                     note=payload.note)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    raw, info = store.issue_key(client.client_id)
    return {"client": client.to_dict(), "key": info.to_dict(), "api_key": raw,
            "warning": "Kalit faqat hozir ko'rsatiladi. Uni xavfsiz joyga saqlang."}


@router.get("/clients/{client_id}")
async def get_client(client_id: str, usage_days: int = 30):
    client = _client_or_404(client_id)
    store = get_client_store()
    return {"client": client.to_dict(), "keys": [k.to_dict() for k in store.list_keys(client_id)],
            "usage": store.usage(client_id, days=usage_days)}


@router.patch("/clients/{client_id}")
async def update_client(client_id: str, payload: ClientUpdate):
    _client_or_404(client_id)
    try:
        client = get_client_store().update_client(client_id, **payload.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"client": client.to_dict()}


@router.post("/clients/{client_id}/keys", status_code=201)
async def issue_key(client_id: str, payload: KeyCreate):
    """A new key for rotation: issue, switch the integration to it, then revoke the old one."""
    _client_or_404(client_id)
    try:
        raw, info = get_client_store().issue_key(client_id, expires_at=payload.expires_at)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"key": info.to_dict(), "api_key": raw,
            "warning": "Kalit faqat hozir ko'rsatiladi. Uni xavfsiz joyga saqlang."}


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: str):
    if not get_client_store().revoke_key(key_id):
        raise HTTPException(status_code=404, detail="Kalit topilmadi yoki allaqachon bekor qilingan.")
    return {"revoked": key_id}
