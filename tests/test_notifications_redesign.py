"""Tests for notifications redesign: stable unit IDs, unit text archive, doc_changes, watcher auto-resolve and API enrichment."""

import copy
import json
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.editorial import service as svc
from src.editorial.doc_watch import (
    archive_law_texts,
    doc_changes,
    doc_change_summary,
    doc_snapshot,
    refresh_doc_link,
)
from src.editorial.store import EditorialStore
from src.editorial.watch import check_legal_links
from src.ingestion.corpus_builder import CorpusBuilder, SourceSpec
from src.ingestion.lex_structured import LexDocument, LexUnit
from src.schema.canonical import ArticleStatus, CanonicalArticle
from src.storage.hybrid_store import HybridStore


def _make_article(cid: str, text_uz: str, status: str = "active",
                  law_id: str = "law_test", article_number: str = "1-modda") -> CanonicalArticle:
    art = CanonicalArticle(
        canonical_id=cid,
        metadata={
            "law_id": law_id,
            "law_title": {"uz": "Nogironlar huquqlari to'g'risida qonun"},
            "law_number": "O'RQ-641",
            "article_number": article_number,
            "article_title": {"uz": f"{article_number} sarlavhasi"},
            "source_url": f"https://lex.uz/docs/1#{cid}",
            "effective_date": "2024-01-01",
            "last_verified_date": "2024-01-01",
            "source_hash": "sha256:placeholder",
            "status": status,
            "category": "disability_rights",
            "source_type": "lex",
        },
        translations={"uz": text_uz},
    )
    art.metadata.source_hash = art.calculate_source_hash()
    return art


@pytest.fixture()
def store(tmp_path):
    return HybridStore(str(tmp_path / "store"))


@pytest.fixture()
def editorial(tmp_path):
    return EditorialStore(str(tmp_path / "editorial.db"))


# -- 1. corpus_builder barqaror id (1-band) -----------------------------------------------------
def test_corpus_builder_stable_ids():
    """
    Soxta LexDocument (bitta ilovada ikkita '1-band', birinchisi umumiy texnik norma,
    ikkinchisi nogironlik haqida).
    'all' va 'disability_articles' rejimlarida kiritilgan 2-bandning id si bir xil bo'lishi shart.
    """
    doc = LexDocument(
        doc_id="12345",
        url="https://lex.uz/docs/12345",
        title="Texnik reglament",
        number="VMQ-100",
        units=[
            LexUnit(
                kind="annex_clause",
                number="1",
                annex_number="3",
                text="Binolarning zilzilabardoshlik umumiy texnik talablari belgilansin.",
            ),
            LexUnit(
                kind="annex_clause",
                number="1",
                annex_number="3",
                text="Nogironligi bo'lgan shaxslar uchun binolarga kirishda maxsus pandus va qulayliklar bo'lishi shart.",
            ),
        ],
    )
    builder = CorpusBuilder(today="2026-10-13")

    spec_all = SourceSpec(lex_id="12345", law_id="law_tech", include="all")
    arts_all, _ = builder.to_articles(doc, spec_all)
    assert len(arts_all) == 2
    # 1-band takrori _2 suffiksini olishi kerak
    cid_second_in_all = arts_all[1].canonical_id
    assert cid_second_in_all.endswith("_2")

    spec_dis = SourceSpec(lex_id="12345", law_id="law_tech", include="disability_articles")
    arts_dis, _ = builder.to_articles(doc, spec_dis)
    assert len(arts_dis) == 1
    # disability_articles filtrida 1-unit elangan bo'lsa ham, 2-unitning ID si o'zgarmasligi shart!
    assert arts_dis[0].canonical_id == cid_second_in_all


# -- 2. Matn arxivi (unit_text_archive) ---------------------------------------------------------
def test_unit_text_archive(editorial):
    rows = [
        ("hash_aaa", "1-band", "Birinchi bandning asl matni."),
        ("hash_bbb", "2-band", "Ikkinchi bandning asl matni."),
    ]
    editorial.archive_unit_texts(rows)

    # Takroriy arxivlash xato bermasligi kerak (INSERT OR IGNORE)
    editorial.archive_unit_texts(rows)

    retrieved = editorial.get_archived_texts(["hash_aaa", "hash_bbb", "hash_missing"])
    assert retrieved["hash_aaa"] == ("1-band", "Birinchi bandning asl matni.")
    assert retrieved["hash_bbb"] == ("2-band", "Ikkinchi bandning asl matni.")
    assert "hash_missing" not in retrieved


# -- 3. doc_changes ssenariylari ---------------------------------------------------------------
def test_doc_changes_id_drift(store, editorial):
    """id ko'chishi (bir xil hashlar, boshqa id lar) -> real=False."""
    art1 = _make_article("law_test_app_1_art_1", "Birinchi band matni.", article_number="1-band")
    art2 = _make_article("law_test_app_1_art_2", "Ikkinchi band matni.", article_number="2-band")
    store.fts_store.upsert_article(art1)
    store.fts_store.upsert_article(art2)

    archive_law_texts(store, editorial, "law_test")

    # Snapshotda ID lar boshqacha edi, lekin matn hash lari aynan art1 va art2 ning hashi
    old_state = {
        "law_test_app_1_art_1_old": f"{art1.metadata.source_hash}|active",
        "law_test_app_1_art_2_old": f"{art2.metadata.source_hash}|active",
    }
    changes = doc_changes(store, editorial, "law_test", json.dumps(old_state))

    assert changes["real"] is False
    assert len(changes["changed"]) == 0
    assert len(changes["removed"]) == 0
    assert len(changes["repealed"]) == 0


def test_doc_changes_text_changed(store, editorial):
    """Band matni o'zgardi -> changed + arxivdan old_text."""
    art1 = _make_article("law_test_art_1", "Eski matn mazmuni.", article_number="1-modda")
    store.fts_store.upsert_article(art1)
    old_hash = art1.metadata.source_hash
    archive_law_texts(store, editorial, "law_test")

    # Endi band matnini o'zgartiramiz
    art1_new = _make_article("law_test_art_1", "Yangi tahrirdagi matn mazmuni.", article_number="1-modda")
    store.fts_store.upsert_article(art1_new)

    old_state = {"law_test_art_1": f"{old_hash}|active"}
    changes = doc_changes(store, editorial, "law_test", json.dumps(old_state))

    assert changes["real"] is True
    assert len(changes["changed"]) == 1
    assert changes["changed"][0]["canonical_id"] == "law_test_art_1"
    assert changes["changed"][0]["old_text"] == "Eski matn mazmuni."
    assert changes["changed"][0]["new_text"] == "Yangi tahrirdagi matn mazmuni."


def test_doc_changes_removed(store, editorial):
    """Band yo'qoldi -> removed."""
    art1 = _make_article("law_test_art_1", "1-modda matni.", article_number="1-modda")
    art2 = _make_article("law_test_art_2", "2-modda matni.", article_number="2-modda")
    store.fts_store.upsert_article(art1)
    store.fts_store.upsert_article(art2)
    old_h1, old_h2 = art1.metadata.source_hash, art2.metadata.source_hash
    archive_law_texts(store, editorial, "law_test")

    # 2-moddani store'dan o'chiramiz
    store.fts_store.delete_article("law_test_art_2")

    old_state = {
        "law_test_art_1": f"{old_h1}|active",
        "law_test_art_2": f"{old_h2}|active",
    }
    changes = doc_changes(store, editorial, "law_test", json.dumps(old_state))

    assert changes["real"] is True
    assert len(changes["removed"]) == 1
    assert changes["removed"][0]["canonical_id"] == "law_test_art_2"
    assert changes["removed"][0]["old_text"] == "2-modda matni."


def test_doc_changes_repealed(store, editorial):
    """Band repealed -> repealed."""
    art1 = _make_article("law_test_art_1", "1-modda matni.", status="active", article_number="1-modda")
    store.fts_store.upsert_article(art1)
    old_hash = art1.metadata.source_hash
    archive_law_texts(store, editorial, "law_test")

    # Endi repealed qilamiz
    art1_rep = _make_article("law_test_art_1", "1-modda matni.", status="repealed", article_number="1-modda")
    store.fts_store.upsert_article(art1_rep)

    old_state = {"law_test_art_1": f"{old_hash}|active"}
    changes = doc_changes(store, editorial, "law_test", json.dumps(old_state))

    assert changes["real"] is True
    assert len(changes["repealed"]) == 1
    assert changes["repealed"][0]["canonical_id"] == "law_test_art_1"


def test_doc_changes_only_added(store, editorial):
    """Faqat yangi bandlar -> real=False, added bor."""
    art1 = _make_article("law_test_art_1", "1-modda matni.", article_number="1-modda")
    store.fts_store.upsert_article(art1)
    old_hash = art1.metadata.source_hash
    archive_law_texts(store, editorial, "law_test")

    # 2-modda qo'shildi
    art2 = _make_article("law_test_art_2", "Yangi 2-modda matni.", article_number="2-modda")
    store.fts_store.upsert_article(art2)

    old_state = {"law_test_art_1": f"{old_hash}|active"}
    changes = doc_changes(store, editorial, "law_test", json.dumps(old_state))

    assert changes["real"] is False
    assert len(changes["changed"]) == 0
    assert len(changes["removed"]) == 0
    assert len(changes["repealed"]) == 0
    assert len(changes["added"]) == 1
    assert changes["added"][0]["canonical_id"] == "law_test_art_2"


# -- 4. check_legal_links kuzatuvchi testlari ---------------------------------------------------
def test_check_legal_links_auto_resolve(store, editorial):
    """id ko'chishi sababli ochiq document_amended bildirishnomasi auto_resolved bo'ladi."""
    art1 = _make_article("law_test_art_1", "Birinchi band matni.", article_number="1-band")
    store.fts_store.upsert_article(art1)
    archive_law_texts(store, editorial, "law_test")

    # Link qo'shamiz (eski snapshot bilan)
    old_state = {"law_test_art_old": f"{art1.metadata.source_hash}|active"}
    link = editorial.add_link(
        owner_type="huquqplus",
        owner_id="uz:101",
        canonical_id="law:law_test",
        law_id="law_test",
        article_label="Test qonuni",
        snapshot_text=json.dumps(old_state),
        snapshot_hash="sha256:old_agg",
        snapshot_status="active",
    )

    # Ochiq bildirishnoma yaratamiz
    editorial.create_notification(
        kind="document_amended",
        owner_type="huquqplus",
        owner_id="uz:101",
        canonical_id="law:law_test",
        old_hash="sha256:old_agg",
        new_hash="sha256:new_agg",
        old_text=json.dumps(old_state),
        new_text="summary",
    )
    assert editorial.count_open_notifications() == 1

    res = check_legal_links(store, editorial)
    assert res["auto_resolved"] >= 1
    assert editorial.count_open_notifications() == 0


def test_check_legal_links_only_added_rebased(store, editorial):
    """Faqat qo'shilgan bandlar -> bildirishnoma yo'q, rebased += 1."""
    art1 = _make_article("law_test_art_1", "1-modda matni.", article_number="1-modda")
    store.fts_store.upsert_article(art1)
    archive_law_texts(store, editorial, "law_test")

    # Havola yaratamiz
    link = editorial.add_link(
        owner_type="huquqplus",
        owner_id="uz:102",
        canonical_id="law:law_test",
        law_id="law_test",
        article_label="Test qonuni",
        snapshot_text="",
        snapshot_hash="",
        snapshot_status="active",
    )
    refresh_doc_link(store, editorial, link)

    # Endi 2-modda qo'shildi
    art2 = _make_article("law_test_art_2", "2-modda yangi matni.", article_number="2-modda")
    store.fts_store.upsert_article(art2)

    res = check_legal_links(store, editorial)
    assert res["new_notifications"] == 0
    assert res["rebased"] >= 1
    assert editorial.count_open_notifications() == 0


# -- 5. router notifications API boyitish -------------------------------------------------------
def test_router_notifications_enriched(store, editorial, monkeypatch):
    """list_notifications endpointi changes, added_count, ai_paused, owner_kind, law_label qaytaradi."""
    from src.editorial import router as ed_router
    monkeypatch.setattr(ed_router, "_get_editorial", lambda: editorial)
    monkeypatch.setattr(ed_router, "_get_store", lambda: store)

    art1 = _make_article("law_test_art_1", "Eski matn.", article_number="1-modda")
    store.fts_store.upsert_article(art1)
    old_hash = art1.metadata.source_hash
    archive_law_texts(store, editorial, "law_test")

    # Link va bildirishnoma
    editorial.add_link(
        owner_type="huquqplus",
        owner_id="uz:200",
        canonical_id="law_test_art_1",
        law_id="law_test",
        article_label="1-modda",
        snapshot_text="Eski matn.",
        snapshot_hash=old_hash,
        snapshot_status="active",
    )

    art1_new = _make_article("law_test_art_1", "Yangi matn.", article_number="1-modda")
    store.fts_store.upsert_article(art1_new)

    notif = editorial.create_notification(
        kind="norm_amended",
        owner_type="huquqplus",
        owner_id="uz:200",
        canonical_id="law_test_art_1",
        old_hash=old_hash,
        new_hash=art1_new.metadata.source_hash,
        old_text="Eski matn.",
        new_text="Yangi matn.",
    )
    assert notif is not None

    with TestClient(app) as c:
        resp = c.get("/api/v1/admin/editorial/notifications?status=open")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) >= 1
        item = data["items"][0]
        assert item["owner_kind"] == "huquqplus"
        assert "changes" in item
        assert len(item["changes"]) == 1
        assert item["changes"][0]["kind"] == "amended"
        assert item["changes"][0]["old_text"] == "Eski matn."
        assert item["changes"][0]["new_text"] == "Yangi matn."
        assert item["ai_paused"] is True
