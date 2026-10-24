"""
Tests for Huquq+ sync module: full_sync, webhook queue, lex_ref resolution,
editorial link lifecycle & notifications, retrieval ordering & gating, admin API, scheduler.
Tarmoqsiz: tests/fixtures/huquqplus/* va soxta get_json yordamida.
"""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.clients.openrouter import OpenRouterClient
from src.config import settings
from src.editorial import service as svc
from src.editorial.retrieval import ensure_curated_contexts
from src.editorial.store import EditorialStore
from src.editorial.watch import check_legal_links
from src.ingestion.huquqplus_client import HuquqPlusClient, parse_lex_ref
from src.integrations.huquqplus_sync import (
    purge_disallowed_languages,
    full_sync, get_lex_index, list_synced_posts, process_queue, reset_lex_index_cache, resolve_lex_ref, suspend_post,
    unsuspend_post, upsert_post,
)
from src.integrations.huquqplus_webhook import WebhookQueue
from src.retrieval.reranker import RetrievedArticleContext
from src.schema.canonical import ArticleMetadata, ArticleStatus, CanonicalArticle
from src.storage.hybrid_store import HybridStore
from src.storage.sqlite_utils import connect as sqlite_connect

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "huquqplus"


def _load_json(filename: str):
    with open(FIXTURES_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


def _fake_client_factory(posts_dict=None):
    """
    Tarmoqsiz HuquqPlusClient: fixture ma'lumotlarini qaytaradi.
    """
    categories_uz = _load_json("categories.json")
    categories_ru = _load_json("categories_ru.json")
    post_2966 = _load_json("post_2966_uz.json")

    posts_map = {2966: post_2966}
    if posts_dict:
        posts_map.update(posts_dict)

    def fake_get_json(url: str):
        if "/categories" in url:
            if "lang=ru" in url:
                return categories_ru, {"x-wp-totalpages": "1"}
            return categories_uz, {"x-wp-totalpages": "1"}

        if "/posts?" in url or url.endswith("/posts"):
            if "_fields=id,modified,categories" in url:
                items = [
                    {"id": pid, "modified": p.get("modified"), "categories": p.get("categories", [48])}
                    for pid, p in posts_map.items()
                ]
                return items, {"x-wp-totalpages": "1"}
            # Fetch posts list
            if "include=" in url:
                include_part = url.split("include=")[1].split("&")[0]
                inc_ids = [int(x) for x in include_part.split(",") if x.isdigit()]
                return [posts_map[i] for i in inc_ids if i in posts_map], {"x-wp-totalpages": "1"}
            return list(posts_map.values()), {"x-wp-totalpages": "1"}

        if "/posts/" in url:
            pid_str = url.split("/posts/")[1].split("?")[0]
            if pid_str.isdigit() and int(pid_str) in posts_map:
                return posts_map[int(pid_str)], {}
            raise Exception("404 Not Found")

        return [], {}

    return HuquqPlusClient(get_json=fake_get_json)


@pytest.fixture()
def custom_store(tmp_path):
    s = HybridStore(str(tmp_path / "store"))
    s._default_client = OpenRouterClient()
    return s


@pytest.fixture()
def custom_editorial(tmp_path):
    return EditorialStore(str(tmp_path / "editorial.db"))


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "huquqplus.db"


def _create_lex_norm(
    cid: str,
    doc_id: str,
    element_id: str,
    text: str = "Tibbiy-ijtimoiy ekspertiza xizmati to'g'risida nizom normasi.",
    source_element_ids=None,
) -> CanonicalArticle:
    source_elem_ids = source_element_ids or ([element_id] if element_id else [])
    art = CanonicalArticle(
        canonical_id=cid,
        schema_version="1.2",
        metadata=ArticleMetadata(
            law_id=f"law_lex_{doc_id.lstrip('-')}",
            law_title={"uz": "VMQ-62-son"},
            law_number="VMQ-62",
            article_number="1-modda",
            article_title={"uz": "Ekspertiza tartibi"},
            source_url=f"https://lex.uz/ru/docs/{doc_id}",
            effective_date="2022-02-08",
            last_verified_date="2022-02-08",
            source_hash="placeholder",
            status=ArticleStatus.ACTIVE,
            category="medical_social_expertise",
            disability_types=["general"],
            beneficiary_type=["individual"],
            source_type="lex",
            source_element_id=element_id,
            source_element_ids=source_elem_ids,
        ),
        translations={"uz": text},
    )
    art.metadata.source_hash = art.calculate_source_hash()
    return art


# -- 1. Lex.uz havola -> modda resolution ---------------------------------------------------------
@pytest.mark.asyncio
async def test_resolve_lex_ref_element_and_unresolved(custom_store):
    reset_lex_index_cache()
    # element_id = "-5853923" va inner element_id = "-5853999" bo'lgan lex article
    norm = _create_lex_norm(
        cid="lex_vmq62_art_1",
        doc_id="-5852486",
        element_id="-5853923",
        source_element_ids=["-5853923", "-5853999"],
    )
    await custom_store.index_article(norm)

    # 1. Element ID topiladi
    ref1 = parse_lex_ref("https://lex.uz/ru/docs/-5852486#-5853923")
    assert ref1 is not None
    resolved = resolve_lex_ref(custom_store, ref1)
    assert resolved == "lex_vmq62_art_1"

    # 2. Ichki element ID ham topiladi
    ref_inner = parse_lex_ref("https://lex.uz/ru/docs/-5852486#-5853999")
    assert resolve_lex_ref(custom_store, ref_inner) == "lex_vmq62_art_1"

    # 3. Hujjat darajasidagi havola (element_id yo'q) -> None (unresolved)
    ref_doc = parse_lex_ref("https://lex.uz/uz/docs/-7021644")
    assert ref_doc is not None
    assert resolve_lex_ref(custom_store, ref_doc) is None


# -- 2. Full Sync & Chunks ------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_full_sync_and_chunking(custom_store, custom_editorial, db_path):
    reset_lex_index_cache()
    # Lex normani store ga qo'shamiz
    norm = _create_lex_norm("lex_vmq62_art_1", "-5852486", "-5853923")
    await custom_store.index_article(norm)

    hp_client = _fake_client_factory()

    # Full sync ishga tushirish
    res = await full_sync(client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)
    assert res["status"] in ("success", "partial_success")
    assert res["added"] >= 1

    # Bo'laklar store'da mavjudligini tekshirish
    hp_1 = custom_store.get_article("hp_uz_2966_1")
    assert hp_1 is not None
    assert hp_1.metadata.source_type == "huquqplus"
    assert hp_1.metadata.law_number == "Huquq+"
    assert hp_1.metadata.law_id == "huquqplus_uz_2966"
    assert "Kattalarda nogironlik" in hp_1.metadata.law_title["uz"]
    assert hp_1.metadata.article_number == "1-qism"
    # Resolve bo'lgan cross_references
    ref_cids = [r.target_canonical_id for r in hp_1.metadata.cross_references]
    assert "lex_vmq62_art_1" in ref_cids

    # Editorial legal_links da bog'langanligini tekshirish
    links = custom_editorial.list_links(owner_type="huquqplus", owner_id="uz:2966")
    assert len(links) >= 1
    assert any(l["canonical_id"] == "lex_vmq62_art_1" for l in links)


# -- 3. Ikkinchi sync o'zgarishsiz bo'lsa qayta embed yo'q ------------------------------------------
@pytest.mark.asyncio
async def test_sync_no_changes_no_reembed(custom_store, custom_editorial, db_path):
    reset_lex_index_cache()
    norm = _create_lex_norm("lex_vmq62_art_1", "-5852486", "-5853923")
    await custom_store.index_article(norm)

    hp_client = _fake_client_factory()
    await full_sync(client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)

    # Ikkinchi sync
    with patch.object(custom_store, "index_articles_batch", wraps=custom_store.index_articles_batch) as mock_index:
        res2 = await full_sync(client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)
        assert res2["added"] == 0
        assert res2["updated"] == 0
        assert mock_index.call_count == 0


# -- 4. Modified o'zgardi, lekin content bir xil -> embed yo'q ---------------------------------------
@pytest.mark.asyncio
async def test_modified_changed_content_same_no_embed(custom_store, custom_editorial, db_path):
    reset_lex_index_cache()
    norm = _create_lex_norm("lex_vmq62_art_1", "-5852486", "-5853923")
    await custom_store.index_article(norm)

    post_dict = copy.deepcopy(_load_json("post_2966_uz.json"))
    hp_client = _fake_client_factory({2966: post_dict})
    await full_sync(client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)

    # Faqat modified sanasini o'zgartiramiz, kontent va sarlavha bir xil
    post_dict["modified"] = "2026-10-12T12:00:00"
    post_dict["modified_gmt"] = "2026-10-12T07:00:00"
    hp_client2 = _fake_client_factory({2966: post_dict})

    with patch.object(custom_store, "index_articles_batch", wraps=custom_store.index_articles_batch) as mock_index:
        res = await full_sync(client=hp_client2, store=custom_store, editorial=custom_editorial, db_path=db_path)
        assert res["updated"] == 1
        assert mock_index.call_count == 0


# -- 5. Kontent o'zgardi -> bo'laklar yangilandi, eski ortiqchalar o'chdi, bildirishnoma yopildi -----
@pytest.mark.asyncio
async def test_content_changed_replaces_units_and_resolves_open_notif(custom_store, custom_editorial, db_path):
    reset_lex_index_cache()
    norm = _create_lex_norm("lex_vmq62_art_1", "-5852486", "-5853923")
    await custom_store.index_article(norm)

    post_dict = copy.deepcopy(_load_json("post_2966_uz.json"))
    hp_client = _fake_client_factory({2966: post_dict})
    await full_sync(client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)

    # Dastlabki bo'laklar sonini ko'ramiz
    posts, _ = list_synced_posts(db_path=db_path)
    initial_units = posts[0]["units_count"]
    assert initial_units > 1

    # Owner uchun sun'iy ochiq bildirishnoma yaratamiz
    custom_editorial.create_notification(
        kind="norm_amended",
        owner_type="huquqplus",
        owner_id="uz:2966",
        canonical_id="lex_vmq62_art_1",
        old_hash="h1",
        new_hash="h2",
        old_text="old",
        new_text="new",
    )
    assert len(custom_editorial.open_notifications_for_owner(owner_type="huquqplus", owner_id="uz:2966")) == 1

    # Endi post kontentini qisqartiramiz (faqat 1 ta kichik bo'lak hosil bo'ladi)
    post_dict["content"]["rendered"] = "<p>Juda qisqa yangi matn.</p>"
    post_dict["modified"] = "2026-10-12T15:00:00"
    hp_client2 = _fake_client_factory({2966: post_dict})

    await full_sync(client=hp_client2, store=custom_store, editorial=custom_editorial, db_path=db_path)

    # Bo'laklar yangilandi: 1-bo'lak bor, lekin 2-bo'lak store'dan o'chgan bo'lishi kerak
    assert custom_store.get_article("hp_uz_2966_1") is not None
    assert custom_store.get_article("hp_uz_2966_2") is None

    # Ochiq bildirishnoma yopilganligini tekshiramiz
    assert len(custom_editorial.open_notifications_for_owner(owner_type="huquqplus", owner_id="uz:2966")) == 0


# -- 6. Post yo'qoldi -> store va editorial dan o'chiriladi ----------------------------------------
@pytest.mark.asyncio
async def test_post_removed_deletes_from_store(custom_store, custom_editorial, db_path):
    reset_lex_index_cache()
    norm = _create_lex_norm("lex_vmq62_art_1", "-5852486", "-5853923")
    await custom_store.index_article(norm)

    hp_client = _fake_client_factory()
    await full_sync(client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)
    assert custom_store.get_article("hp_uz_2966_1") is not None

    # Postlar ro'yxatidan yo'qoldi
    empty_client = HuquqPlusClient(get_json=lambda url: ([], {"x-wp-totalpages": "0"}))
    await full_sync(client=empty_client, store=custom_store, editorial=custom_editorial, db_path=db_path)

    # Store dan o'chgan bo'lishi kerak
    assert custom_store.get_article("hp_uz_2966_1") is None
    # Editorial links ham tozalangan
    assert len(custom_editorial.list_links(owner_type="huquqplus", owner_id="uz:2966")) == 0


# -- 7. Webhook Queue: process_queue (upsert & delete) --------------------------------------------
@pytest.mark.asyncio
async def test_webhook_queue_process(custom_store, custom_editorial, db_path):
    reset_lex_index_cache()
    norm = _create_lex_norm("lex_vmq62_art_1", "-5852486", "-5853923")
    await custom_store.index_article(norm)

    queue = WebhookQueue(str(db_path))
    hp_client = _fake_client_factory()

    # 1. Enqueue upsert
    queue.enqueue("event-12345678", "upsert", 2966, "uz")
    res = await process_queue(limit=10, client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)
    assert res["processed"] == 1
    assert res["errors"] == 0
    assert custom_store.get_article("hp_uz_2966_1") is not None

    # 2. Enqueue delete
    queue.enqueue("event-87654321", "delete", 2966, "uz")
    res_del = await process_queue(limit=10, client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)
    assert res_del["processed"] == 1
    assert custom_store.get_article("hp_uz_2966_1") is None


# -- 8. Suspend / Unsuspend ------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_suspend_and_unsuspend(custom_store, custom_editorial, db_path):
    reset_lex_index_cache()
    norm = _create_lex_norm("lex_vmq62_art_1", "-5852486", "-5853923")
    await custom_store.index_article(norm)

    hp_client = _fake_client_factory()
    await full_sync(client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)
    assert custom_store.get_article("hp_uz_2966_1") is not None

    # Suspend post
    ok = suspend_post("uz:2966", store=custom_store, db_path=db_path)
    assert ok is True
    assert custom_store.get_article("hp_uz_2966_1") is None

    # Unsuspend post
    ok_unsuspend = await unsuspend_post("uz:2966", client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)
    assert ok_unsuspend is True
    assert custom_store.get_article("hp_uz_2966_1") is not None


# -- 9. Watch & Resolve: keep, unpublish, edited, delete (422) ------------------------------------
@pytest.mark.asyncio
async def test_watch_and_resolve_huquqplus_actions(custom_store, custom_editorial, db_path):
    reset_lex_index_cache()
    norm = _create_lex_norm("lex_vmq62_art_1", "-5852486", "-5853923")
    await custom_store.index_article(norm)

    hp_client = _fake_client_factory()
    await full_sync(client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)

    # Lex moddasini o'zgartiramiz -> watch bildirishnoma yaratishi kerak
    norm_updated = _create_lex_norm("lex_vmq62_art_1", "-5852486", "-5853923", text="Tahrirlangan yangi qonun normasi.")
    await custom_store.index_article(norm_updated)

    watch_res = check_legal_links(custom_store, custom_editorial)
    assert watch_res["new_notifications"] >= 1

    notifs = custom_editorial.open_notifications_for_owner(owner_type="huquqplus", owner_id="uz:2966")
    assert len(notifs) >= 1
    notif = notifs[0]

    # Delete huquqplus uchun ValueError (routerda 422) beradi
    with pytest.raises(ValueError):
        svc.resolve_notification_action(custom_store, custom_editorial, notif, action="delete")

    # Unpublish (RAG dan vaqtincha olish)
    with patch("src.integrations.huquqplus_sync.get_huquqplus_db_path", return_value=db_path):
        resolved_unpub = svc.resolve_notification_action(custom_store, custom_editorial, notif, action="unpublish")
        assert resolved_unpub["status"] == "resolved"
        assert custom_store.get_article("hp_uz_2966_1") is None

    # Qayta aktivlashtirib, keep harakatini tekshiramiz
    await unsuspend_post("uz:2966", client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)
    notif2 = custom_editorial.create_notification(
        kind="norm_amended",
        owner_type="huquqplus",
        owner_id="uz:2966",
        canonical_id="lex_vmq62_art_1",
        old_hash="h1",
        new_hash="h2",
        old_text="old",
        new_text="new",
    )
    resolved_keep = svc.resolve_notification_action(custom_store, custom_editorial, notif2, action="keep")
    assert resolved_keep["status"] == "resolved"


# -- 10. Retrieval: zaif hp_ tashlanadi, ochiq bildirishnomali tashlanadi, kuchli hp_ lex qo'shiladi
@pytest.mark.asyncio
async def test_retrieval_huquqplus_contexts(custom_store, custom_editorial, db_path):
    reset_lex_index_cache()
    norm = _create_lex_norm("lex_vmq62_art_1", "-5852486", "-5853923")
    await custom_store.index_article(norm)

    hp_client = _fake_client_factory()
    await full_sync(client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)
    hp_art = custom_store.get_article("hp_uz_2966_1")
    assert hp_art is not None

    with patch("src.integrations.huquqplus_sync.get_huquqplus_db_path", return_value=db_path):
        # 1. Zaif rerank bahosi -> tashlanadi
        weak_ctx = RetrievedArticleContext(article=hp_art, rerank_score=0.20, final_score=0.20, source_tag="hybrid")
        res_weak = ensure_curated_contexts([weak_ctx], custom_store, custom_editorial, min_rerank_score=0.70)
        assert len(res_weak) == 0

        # 2. Kuchli rerank bahosi -> qoladi va uning linked lex normasi qo'shiladi
        strong_ctx = RetrievedArticleContext(article=hp_art, rerank_score=0.85, final_score=0.85, source_tag="hybrid")
        res_strong = ensure_curated_contexts([strong_ctx], custom_store, custom_editorial, min_rerank_score=0.70)
        assert len(res_strong) >= 2
        # Avval legal_basis bo'lgan lex_norm, Huquq+ maqolasi qonundan keyin turadi
        assert res_strong[0].article.canonical_id == "lex_vmq62_art_1"
        assert res_strong[0].rerank_score is None
        assert res_strong[-1].article.canonical_id == "hp_uz_2966_1"

        # 3. Ochiq bildirishnomasi bo'lsa -> tashlanadi
        custom_editorial.create_notification(
            kind="norm_amended",
            owner_type="huquqplus",
            owner_id="uz:2966",
            canonical_id="lex_vmq62_art_1",
            old_hash="h1",
            new_hash="h2",
            old_text="old",
            new_text="new",
        )
        res_notif = ensure_curated_contexts([strong_ctx], custom_store, custom_editorial, min_rerank_score=0.70)
        assert len(res_notif) == 0


# -- 11. Admin Endpoints Authentication & 422 on Delete --------------------------------------------
def test_admin_huquqplus_endpoints_auth():
    test_client = TestClient(app)

    remote_header = {"X-Forwarded-For": "203.0.113.19"}
    with patch.object(settings, "ADMIN_API_KEY", "secret-test-key"):
        # Kalitsiz masofaviy so'rov
        res = test_client.get("/api/v1/admin/huquqplus/status", headers=remote_header)
        assert res.status_code in (401, 403)

        # Noto'g'ri kalit
        res_wrong = test_client.get("/api/v1/admin/huquqplus/status", headers={**remote_header, "X-Admin-Key": "wrong"})
        assert res_wrong.status_code in (401, 403)

        # To'g'ri kalit
        auth_headers = {**remote_header, "X-Admin-Key": "secret-test-key"}
        res_auth = test_client.get("/api/v1/admin/huquqplus/status", headers=auth_headers)
        assert res_auth.status_code == 200

        res_posts = test_client.get("/api/v1/admin/huquqplus/posts", headers=auth_headers)
        assert res_posts.status_code == 200

        with patch("src.api.routes.huquqplus_admin.full_sync", new_callable=AsyncMock):
            res_sync_auth = test_client.post("/api/v1/admin/huquqplus/sync", headers=auth_headers)
            assert res_sync_auth.status_code == 202

        # Huquq+ bildirishnomasi uchun delete harakati 422 qaytarishi kerak
        editorial = EditorialStore()
        notif = editorial.create_notification(
            kind="norm_amended",
            owner_type="huquqplus",
            owner_id="uz:2966",
            canonical_id="lex_vmq62_art_1",
            old_hash="h1",
            new_hash="h2",
            old_text="old",
            new_text="new",
        )
        assert notif is not None
        res_del = test_client.post(
            f"/api/v1/admin/editorial/notifications/{notif['id']}/resolve",
            json={"action": "delete"},
            headers=auth_headers
        )
        assert res_del.status_code == 422


# -- 12. Scheduler Mock rejimida ishlamasligi ------------------------------------------------------
def test_scheduler_disabled_in_mock_mode():
    with patch.object(settings, "MOCK_EXTERNAL_APIS", True):
        # MOCK_EXTERNAL_APIS=True bo'lganda scheduler vazifasi ishga tushmasligi kerak
        assert settings.MOCK_EXTERNAL_APIS is True
        # app lifespan shartida: if settings.HUQUQPLUS_SYNC_ENABLED and not settings.MOCK_EXTERNAL_APIS:
        # demak task yaratilmaydi


# -- Regressions found in review -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_suspended_post_stays_suspended_when_only_the_timestamp_moves(custom_store, custom_editorial, db_path):
    reset_lex_index_cache()
    hp_client = _fake_client_factory()
    await full_sync(client=hp_client, store=custom_store, editorial=custom_editorial, db_path=db_path)
    suspend_post("uz:2966", store=custom_store, db_path=db_path)
    post = hp_client.fetch_post(2966, lang="uz")
    post.modified = "2030-01-01T00:00:00"          # editor saved the post without changing its text
    res = await upsert_post(post, custom_store, custom_editorial, db_path=db_path)
    assert res["action"] == "modified_only"
    assert custom_store.get_article("hp_uz_2966_1") is None


@pytest.mark.asyncio
async def test_listing_that_lost_most_posts_does_not_wipe_the_base(custom_store, custom_editorial, db_path):
    from src.integrations import huquqplus_sync as sync_mod
    reset_lex_index_cache()
    sync_mod.init_huquqplus_db(db_path)
    with sqlite_connect(db_path) as conn:          # six known posts, the listing now returns none
        for i in range(1, 7):
            conn.execute("INSERT INTO hp_posts VALUES (?, 'uz', '2026-01-01', 'h', 't', 'u', 'materials', 'active', "
                         "'[]', '[]', '[]', '2026-01-01')", (i,))

    class EmptyListing:
        def list_post_index(self, lang="uz"):
            return {}

        def fetch_posts(self, lang="uz", ids=None):
            return []

    res = await full_sync(client=EmptyListing(), store=custom_store, editorial=custom_editorial, db_path=db_path)
    assert res["removed"] == 0 and "mass_removal_blocked" in res["message"]
    with sqlite_connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM hp_posts WHERE status = 'active'").fetchone()[0] == 6


@pytest.mark.asyncio
async def test_abandoned_run_does_not_block_sync_forever(custom_store, custom_editorial, db_path):
    from src.integrations import huquqplus_sync as sync_mod
    sync_mod.init_huquqplus_db(db_path)
    with sqlite_connect(db_path) as conn:
        conn.execute("INSERT INTO sync_runs (kind, started_at) VALUES ('full', '2020-01-01T00:00:00+00:00')")
    res = await full_sync(client=_fake_client_factory(), store=custom_store, editorial=custom_editorial,
                          db_path=db_path)
    assert res["status"] in ("success", "partial_success")


@pytest.mark.asyncio
async def test_anchor_outside_any_unit_stays_document_level(custom_store):
    """A heading anchor must not be guessed onto a neighbouring unit (ids are not in document order)."""
    from src.ingestion.huquqplus_client import LexRef
    reset_lex_index_cache()
    await custom_store.index_article(_create_lex_norm("lex_doc_p_1", "-5852486", "-5853930"))
    ref = LexRef(url="https://lex.uz/ru/docs/-5852486#-5853923", doc_id="-5852486", element_id="-5853923",
                 lang="ru", anchor_text="Nizom")
    assert resolve_lex_ref(custom_store, ref) is None
    assert get_lex_index(custom_store).doc_to_law_id["-5852486"] == "law_lex_5852486"


@pytest.mark.asyncio
async def test_russian_edition_links_resolve_to_the_uzbek_unit(custom_store):
    from src.ingestion.huquqplus_client import LexRef
    reset_lex_index_cache()
    norm = _create_lex_norm("law_disability_2020_art_1", "-5049511", "-5053973")
    norm.metadata.ru_document_id = "5049549"
    norm.metadata.ru_element_ids = ["5054659", "5054661"]
    await custom_store.index_article(norm)
    ref = LexRef(url="https://lex.uz/docs/5049549#5054661", doc_id="5049549", element_id="5054661",
                 lang=None, anchor_text="")
    assert resolve_lex_ref(custom_store, ref) == "law_disability_2020_art_1"
    assert get_lex_index(custom_store).doc_to_law_id["5049549"] == "law_lex_5049511"


@pytest.mark.asyncio
async def test_whole_act_reference_is_watched_at_document_level(custom_store, custom_editorial, db_path):
    """An article citing an act without an article anchor is notified when any unit of that act changes."""
    from src.editorial.doc_watch import doc_link_id
    from src.ingestion.huquqplus_client import LexRef
    reset_lex_index_cache()
    a1 = _create_lex_norm("law_x_art_1", "-7021644", "-7021700", text="Birinchi modda matni.")
    a2 = _create_lex_norm("law_x_art_2", "-7021644", "-7021710", text="Ikkinchi modda matni.")
    for a in (a1, a2):
        a.metadata.law_id = "law_x"
        a.metadata.article_number = a.canonical_id[-1] + "-modda"
        a.metadata.source_hash = a.calculate_source_hash()
        await custom_store.index_article(a)
    post = _fake_client_factory().fetch_post(2966, lang="uz")
    post.lex_refs = [LexRef(url="https://lex.uz/uz/docs/-7021644", doc_id="-7021644", element_id=None,
                            lang="uz", anchor_text="")]
    post.content_hash = "sha256:doc-level"
    await upsert_post(post, custom_store, custom_editorial, db_path=db_path)
    links = custom_editorial.list_links(owner_type="huquqplus", owner_id="uz:2966")
    assert [l["canonical_id"] for l in links] == [doc_link_id("law_x")]
    assert check_legal_links(custom_store, custom_editorial)["new_notifications"] == 0

    changed = a2.model_copy(deep=True)
    changed.translations["uz"] = "Ikkinchi modda yangi tahrirda."
    changed.metadata.source_hash = changed.calculate_source_hash()
    custom_store.fts_store.upsert_article(changed)
    assert check_legal_links(custom_store, custom_editorial)["new_notifications"] == 1
    card = custom_editorial.list_notifications(status="open")[0][0]
    assert card["kind"] == "document_amended" and "2-modda" in card["new_text"] and "1-modda" not in card["new_text"]

    svc.resolve_notification_action(custom_store, custom_editorial, card, action="keep")
    assert check_legal_links(custom_store, custom_editorial)["new_notifications"] == 0

    for a in (a1, changed):
        rep = a.model_copy(deep=True)
        rep.metadata.status = ArticleStatus.REPEALED
        custom_store.fts_store.upsert_article(rep)
    check_legal_links(custom_store, custom_editorial)
    card = custom_editorial.list_notifications(status="open")[0][0]
    assert card["kind"] == "norm_repealed"
    with pytest.raises(ValueError, match="kuchini yo'qotgan"):
        svc.resolve_notification_action(custom_store, custom_editorial, card, action="keep")


def test_admin_huquqplus_posts_enrichment(custom_store, db_path):
    from src.integrations.huquqplus_sync import init_huquqplus_db

    test_client = TestClient(app)
    init_huquqplus_db(db_path)

    unresolved_data = [
        {"doc_id": "48496", "law_id": "vmq_62", "url": "https://lex.uz/docs/48496"},
        {"doc_id": "99999", "law_id": None, "url": "https://lex.uz/docs/99999"},
    ]
    with sqlite_connect(db_path) as conn:
        conn.execute("""
            INSERT INTO hp_posts (wp_id, lang, modified, content_hash, title, url, section, status, unit_ids, lex_refs, unresolved_refs, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            101, "uz", "2026-10-10T10:00:00", "hash101", "Sinov maqolasi", "https://huquqplus.uz/p/101",
            "ijtimoiy", "active", "[]", "[]", json.dumps(unresolved_data), "2026-10-10T10:00:00"
        ))

    norm = _create_lex_norm("lex_vmq62_art_1", "48496", "48500")
    norm.metadata.law_id = "vmq_62"
    norm.metadata.law_number = "VMQ-62"
    norm.metadata.law_title = {"uz": "Tibbiy-ijtimoiy ekspertiza xizmati"}
    norm.metadata.source_url = "https://lex.uz/uz/docs/48496#48500"
    custom_store.fts_store.upsert_article(norm)

    with patch("src.integrations.huquqplus_sync.get_huquqplus_db_path", return_value=db_path), \
         patch("src.api.app.get_store", return_value=custom_store):
        res = test_client.get("/api/v1/admin/huquqplus/posts")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 1
        post = next(p for p in data["items"] if p["wp_id"] == 101)
        unresolved = post["unresolved_links"]
        assert len(unresolved) == 2

        # Bog'langan akt: law_label va source_url qo'shilgan
        linked = next(r for r in unresolved if r["law_id"] == "vmq_62")
        assert linked["law_label"] == "VMQ-62 Tibbiy-ijtimoiy ekspertiza xizmati"
        assert linked["source_url"] == "https://lex.uz/uz/docs/48496"

        # Korpusda yo'q akt
        missing = next(r for r in unresolved if not r["law_id"])
        assert "law_label" not in missing

        # Alohida get post endpointi
        res_single = test_client.get("/api/v1/admin/huquqplus/posts/uz/101")
        assert res_single.status_code == 200
        single_post = res_single.json()
        single_linked = next(r for r in single_post["unresolved_links"] if r["law_id"] == "vmq_62")
        assert single_linked["law_label"] == "VMQ-62 Tibbiy-ijtimoiy ekspertiza xizmati"
        assert single_linked["source_url"] == "https://lex.uz/uz/docs/48496"


# -- only the Uzbek posts are synchronized: the Russian version says what the Uzbek one says -------------------------

def _russian_copy(post):
    ru = copy.deepcopy(post)
    ru.lang = "ru"
    ru.title = "Как устанавливается инвалидность у взрослых?"
    ru.text = "Инвалидность устанавливается медико-социальной экспертной комиссией по заявлению гражданина. " * 3
    return ru


@pytest.mark.asyncio
async def test_a_full_sync_asks_for_the_uzbek_posts_only(custom_store, custom_editorial, db_path):
    asked = []

    class Recording:
        def list_post_index(self, lang="uz"):
            asked.append(lang)
            return {}

        def fetch_posts(self, lang="uz", ids=None):
            return []

    await full_sync(client=Recording(), store=custom_store, editorial=custom_editorial, db_path=db_path)
    assert asked == ["uz"]


@pytest.mark.asyncio
async def test_a_russian_post_is_not_indexed(custom_store, custom_editorial, db_path):
    reset_lex_index_cache()
    ru = _russian_copy(_fake_client_factory().fetch_post(2966, lang="uz"))
    res = await upsert_post(ru, custom_store, custom_editorial, db_path=db_path)
    assert res["action"] == "skipped_language" and res["lang"] == "ru"
    assert custom_store.get_article("hp_ru_2966_1") is None
    with sqlite_connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM hp_posts").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_russian_posts_stored_earlier_are_removed_with_their_units_and_links(custom_store, custom_editorial, db_path, monkeypatch):
    reset_lex_index_cache()
    uz = _fake_client_factory().fetch_post(2966, lang="uz")
    monkeypatch.setattr(settings, "HUQUQPLUS_LANGUAGES", "uz,ru")
    await upsert_post(uz, custom_store, custom_editorial, db_path=db_path)
    await upsert_post(_russian_copy(uz), custom_store, custom_editorial, db_path=db_path)
    assert custom_store.get_article("hp_ru_2966_1") is not None and custom_store.get_article("hp_uz_2966_1") is not None

    monkeypatch.setattr(settings, "HUQUQPLUS_LANGUAGES", "uz")
    assert purge_disallowed_languages(custom_store, custom_editorial, db_path=db_path) == 1
    assert custom_store.get_article("hp_ru_2966_1") is None
    assert custom_store.get_article("hp_uz_2966_1") is not None              # the Uzbek post stays
    with sqlite_connect(db_path) as conn:
        assert dict(conn.execute("SELECT lang, status FROM hp_posts").fetchall()) == {"uz": "active", "ru": "deleted"}
    assert purge_disallowed_languages(custom_store, custom_editorial, db_path=db_path) == 0     # nothing is left to remove


@pytest.mark.asyncio
async def test_a_full_sync_also_cleans_up_the_languages_it_no_longer_syncs(custom_store, custom_editorial, db_path, monkeypatch):
    reset_lex_index_cache()
    uz = _fake_client_factory().fetch_post(2966, lang="uz")
    monkeypatch.setattr(settings, "HUQUQPLUS_LANGUAGES", "uz,ru")
    await upsert_post(_russian_copy(uz), custom_store, custom_editorial, db_path=db_path)
    monkeypatch.setattr(settings, "HUQUQPLUS_LANGUAGES", "uz")
    res = await full_sync(client=_fake_client_factory(), store=custom_store, editorial=custom_editorial, db_path=db_path)
    assert res["removed"] >= 1 and custom_store.get_article("hp_ru_2966_1") is None


@pytest.mark.asyncio
async def test_a_webhook_event_of_the_russian_version_is_dropped_without_a_fetch(custom_store, custom_editorial, db_path):
    from src.integrations import huquqplus_sync as sync_mod
    sync_mod.init_huquqplus_db(db_path)
    fetched = []

    class Recording:
        def fetch_post(self, post_id, lang="uz"):
            fetched.append((post_id, lang))
            return None

    pending = [{"id": 1, "event": "upsert", "post_id": 2966, "lang": "ru"}]
    marked = []

    class FakeQueue:
        def __init__(self, path):
            pass

        def pending(self, limit=50):
            return pending

        def mark_done(self, row_id):
            marked.append(row_id)

        def mark_failed(self, row_id, message):
            raise AssertionError(message)

    with patch.object(sync_mod, "WebhookQueue", FakeQueue):
        res = await sync_mod._process_queue_unlocked(10, Recording(), custom_store, custom_editorial, db_path)
    assert res == {"processed": 1, "errors": 0} and marked == [1] and fetched == []
