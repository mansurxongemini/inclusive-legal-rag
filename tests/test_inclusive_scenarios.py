"""
Comprehensive Evaluation of Inclusive Legal RAG on Real Disability Scenarios.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from src.api.app import app


@pytest.mark.asyncio
async def test_tmek_scenario():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "question": "Muddatsiz nogironlik qanday hollarda belgilanadi va TMEK xulosasidan norozi bo'lsa qayerga murojaat qilish kerak?",
            "category": "medical_social_expertise",
            "language": "uz",
            "mode": "plain",
        }
        res = await ac.post("/api/v1/query", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert len(data["clean_answer"]) > 50
        assert len(data["citations"]) > 0
        c_cids = [c["canonical_id"] for c in data["citations"]]
        assert any("tmek" in cid or "disability" in cid for cid in c_cids)


@pytest.mark.asyncio
async def test_tax_scenario():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "question": "II guruh nogironlari uchun daromad va mol-mulk solig'i bo'yicha qanday imtiyozlar bor?",
            "category": "tax_benefits",
            "language": "uz",
            "mode": "plain",
        }
        res = await ac.post("/api/v1/query", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert len(data["clean_answer"]) > 50
        assert len(data["citations"]) > 0


@pytest.mark.asyncio
async def test_prosthetics_scenario():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "question": "Nogironlar aravachasi necha yilda bir marta bepul almashtirib beriladi?",
            "category": "rehabilitation_prosthetics",
            "language": "uz",
            "mode": "plain",
        }
        res = await ac.post("/api/v1/query", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert len(data["clean_answer"]) > 50
        assert len(data["citations"]) > 0
