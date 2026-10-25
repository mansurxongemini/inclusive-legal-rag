"""Answers, the admin API and the web pages carry no emoji (owner's rule, 2026-10-25)."""
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app

EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF️]")
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_admin_hierarchy_has_no_emoji():
    async with AsyncClient(transport=ASGITransport(app=app, client=("127.0.0.1", 40000)), base_url="http://localhost") as c:
        res = await c.get("/api/v1/admin/hierarchy")
    assert res.status_code == 200 and not EMOJI.search(res.text)


def test_web_pages_and_answer_code_have_no_emoji():
    files = [p for p in (ROOT / "src").rglob("*") if p.suffix in (".py", ".js", ".html", ".css") and "scratch" not in p.parts]
    offenders = [str(p.relative_to(ROOT)) for p in files if EMOJI.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert offenders == []
