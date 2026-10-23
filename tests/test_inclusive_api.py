"""
Automated Test Suite for Inclusive Legal RAG API.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from src.api.app import app
from src.api.auth.api_keys import api_key_manager


@pytest.mark.asyncio
async def test_inclusive_categories():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/inclusive/categories")
        assert res.status_code == 200
        data = res.json()
        assert "categories" in data
        assert "disability_groups" in data
        cat_ids = [c["id"] for c in data["categories"]]
        assert "disability_rights" in cat_ids
        assert "pensions_and_benefits" in cat_ids
        assert "labor_rights" in cat_ids
        assert "medical_social_expertise" in cat_ids


@pytest.mark.asyncio
async def test_inclusive_stats():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/inclusive/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["total_statutory_norms"] > 0
        assert "category_distribution" in data


@pytest.mark.asyncio
async def test_inclusive_norms_search():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/inclusive/norms?limit=10")
        assert res.status_code == 200
        data = res.json()
        assert len(data["norms"]) > 0
        norm = data["norms"][0]
        assert "canonical_id" in norm
        assert "article_number" in norm
        assert "law_title" in norm


@pytest.mark.asyncio
async def test_api_key_lifecycle():
    # 1. Create key
    new_key = api_key_manager.create_key("Unit Test Client", rate_limit=30)
    raw_key = new_key["api_key"]
    key_id = new_key["key_id"]

    # 2. Validate
    rec = api_key_manager.validate_key(raw_key)
    assert rec is not None
    assert rec.key_id == key_id
    assert rec.name == "Unit Test Client"

    # 3. Revoke
    revoked = api_key_manager.revoke_key(key_id)
    assert revoked is True
    assert api_key_manager.validate_key(raw_key) is None


@pytest.mark.asyncio
async def test_inclusive_query_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "question": "I guruh nogironligi bo'lgan xodimlar uchun ish vaqti davomiyligi qancha?",
            "disability_group": "group_1",
            "category": "labor_rights",
            "language": "uz",
            "mode": "plain",
        }
        res = await ac.post("/api/v1/inclusive/query", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert "answer" in data
        assert len(data["answer"]) > 20
        assert data["detected_language"] == "uz"
        assert "citations" in data


@pytest.mark.asyncio
async def test_list_inclusive_documents():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/inclusive/documents")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] > 0
        assert len(data["documents"]) > 0
        first_doc = data["documents"][0]
        assert "law_number" in first_doc
        assert "law_title" in first_doc
        assert "authority" in first_doc
        assert "doc_type" in first_doc
        assert "norm_count" in first_doc
        assert "type_counts" in data
        assert "authority_counts" in data


@pytest.mark.asyncio
async def test_get_document_norms():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. First get documents
        res_docs = await ac.get("/api/v1/inclusive/documents")
        assert res_docs.status_code == 200
        docs = res_docs.json()["documents"]
        assert len(docs) > 0
        law_num = docs[0]["law_number"]

        # 2. Get norms for this document
        res_norms = await ac.get(f"/api/v1/inclusive/documents/{law_num}/norms")
        assert res_norms.status_code == 200
        data = res_norms.json()
        assert data["law_number"] == law_num
        assert data["total_norms"] > 0
        assert len(data["norms"]) == data["total_norms"]
        first_norm = data["norms"][0]
        assert "canonical_id" in first_norm
        assert "text_uz" in first_norm



