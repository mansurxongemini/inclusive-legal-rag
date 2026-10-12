"""Tahririyat moduli testlari: CRUD, bog'lash, nashr, kuzatuv, resolve, endpointlar, refresh, generatsiya."""

import copy

import pytest

from src.clients.openrouter import OpenRouterClient
from src.editorial import service as svc
from src.editorial.store import EditorialStore
from src.editorial.watch import check_legal_links
from src.schema.canonical import ArticleStatus, CanonicalArticle
from src.storage.hybrid_store import HybridStore


def _lex_article(cid: str, text_uz: str, status: str = "active",
                 law_id: str = "law_test", source_type: str = "lex") -> CanonicalArticle:
    return CanonicalArticle(
        canonical_id=cid,
        metadata={
            "law_id": law_id,
            "law_title": {"uz": "Test qonuni"},
            "law_number": "O'RQ-999",
            "article_number": "1-modda",
            "article_title": {"uz": "Test moddasi"},
            "source_url": "https://lex.uz/docs/1",
            "effective_date": "2024-01-01",
            "last_verified_date": "2024-01-01",
            "source_hash": "sha256:placeholder",
            "status": status,
            "category": "general",
            "source_type": source_type,
        },
        translations={"uz": text_uz},
    )


@pytest.fixture()
def store(tmp_path):
    return HybridStore(str(tmp_path / "store"))


@pytest.fixture()
def editorial(tmp_path):
    return EditorialStore(str(tmp_path / "editorial.db"))


@pytest.fixture()
def client():
    return OpenRouterClient()  # mock rejimda (conftest MOCK_EXTERNAL_APIS=true)


async def _seed_lex(store, client, cid="law_test_art_1",
                    text="Nogironligi bo'lgan shaxslarga nafaqa to'lanadi."):
    art = _lex_article(cid, text)
    art.metadata.source_hash = art.calculate_source_hash()
    await store.index_article(art, client=client)
    return store.get_article(cid)


async def _published_answer(store, editorial, client, question="Nafaqa kimga to'lanadi?",
                            text="Nogironligi bo'lgan shaxslarga nafaqa to'lanadi."):
    lex = await _seed_lex(store, client)
    answer = editorial.create_answer(
        question=question, alt_questions=["Nafaqa haqida"],
        answer_md="Nogironligi bo'lgan shaxslarga nafaqa to'lanadi.",
        language="uz", category="general", author="tester",
    )
    snap_text, snap_hash, snap_status = svc.snapshot_of(lex)
    editorial.add_link(owner_type="curated", owner_id=str(answer["id"]),
                       canonical_id=lex.canonical_id, law_id=lex.metadata.law_id,
                       article_label="O'RQ-999 1-modda",
                       snapshot_text=snap_text, snapshot_hash=snap_hash,
                       snapshot_status=snap_status)
    return await svc.publish_answer(store, editorial, answer["id"])


# -- 1. Manba turi ---------------------------------------------------------------------------------
def test_metadata_source_type_defaults_to_lex():
    art = _lex_article("x_art_1", "matn")
    assert art.metadata.source_type == "lex"
    assert art.metadata.published_url is None


# -- 2. CRUD + audit ---------------------------------------------------------------------------------
def test_answer_crud_and_history(editorial):
    created = editorial.create_answer(
        question="Savol matni besh?", alt_questions=["Muqobil savol"],
        answer_md="Javob matni o'n belgidan uzun.", language="uz",
        category="general", author="ali",
    )
    assert created["status"] == "draft"
    assert created["version"] == 1

    items, total = editorial.list_answers(limit=50, offset=0)
    assert total == 1 and items[0]["id"] == created["id"]

    updated = editorial.update_answer(created["id"], {"question": "Yangilangan savol matni?"})
    assert updated["version"] == 2
    history = editorial.get_history(created["id"])
    assert [h["action"] for h in history] == ["create", "edit"]

    assert editorial.delete_answer(created["id"]) is True
    assert editorial.get_answer(created["id"]) is None


# -- 3. Bog'lash qoidalari ----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_link_only_lex_active(store, editorial, client):
    lex = await _seed_lex(store, client)
    answer = editorial.create_answer(
        question="Bog'lash qoidalari?", alt_questions=[],
        answer_md="Javob matni o'n belgidan uzun albatta.", language="uz",
        category="general", author="t",
    )
    # Mavjud bo'lmagan modda
    art, err = svc.validate_link_target(store, "no_such_id")
    assert err == "not_found"
    # Repealed modda
    rep = _lex_article("law_test_art_9", "Eski matn.", status="repealed")
    rep.metadata.source_hash = rep.calculate_source_hash()
    await store.index_article(rep, client=client)
    _, err = svc.validate_link_target(store, "law_test_art_9")
    assert err == "not_active"
    # Curated proyeksiyani bog'lab bo'lmaydi
    await _published_answer(store, editorial, client, question="Boshqa savol matni?")
    _, err = svc.validate_link_target(store, "qa_2")
    assert err == "not_lex"
    # To'g'ri holat: snapshot olinadi
    art, err = svc.validate_link_target(store, lex.canonical_id)
    assert err == "" and art is not None
    text, h, st = svc.snapshot_of(art)
    link = editorial.add_link(owner_type="curated", owner_id=str(answer["id"]),
                              canonical_id=art.canonical_id, law_id=art.metadata.law_id,
                              article_label="O'RQ-999 1-modda",
                              snapshot_text=text, snapshot_hash=h, snapshot_status=st)
    assert link["snapshot_hash"] == art.metadata.source_hash
    assert link["snapshot_text"] == art.get_text("uz")


# -- 4. Nashr uchun asos majburiy + proyeksiya ----------------------------------------------------------
@pytest.mark.asyncio
async def test_publish_requires_basis_and_projects(store, editorial, client, monkeypatch):
    from src.api import app as app_module
    cleared = {"n": 0}

    class _FakeCache:
        def clear(self):
            cleared["n"] += 1

    monkeypatch.setattr(app_module, "get_cache", lambda: _FakeCache())

    answer = editorial.create_answer(
        question="Nashr asosi bormi?", alt_questions=[],
        answer_md="Javob matni o'n belgidan uzun albatta.", language="uz",
        category="general", author="t",
    )
    with pytest.raises(ValueError, match="legal_basis_required"):
        await svc.publish_answer(store, editorial, answer["id"])

    published = await _published_answer(store, editorial, client, question="Nashr asosi bormi?")
    assert published["status"] == "published"
    assert cleared["n"] >= 1
    qa = store.get_article(f"qa_{published['id']}")
    assert qa is not None
    assert qa.metadata.source_type == "curated"
    assert qa.metadata.law_id == "curated_qa"
    assert any(r.target_canonical_id == "law_test_art_1" for r in qa.metadata.cross_references)

    # Unpublish/needs_review/archive/delete store'dan olib tashlaydi
    svc.unproject_answer(store, published["id"])
    assert store.get_article(f"qa_{published['id']}") is None


# -- 5. Kuzatuvchi: amended / repealed / removed + takrorlanmaslik + needs_review -----------------------
@pytest.mark.asyncio
async def test_watch_amended_repealed_removed(store, editorial, client, monkeypatch):
    monkeypatch.setattr("src.config.settings.EDITORIAL_SUSPEND_ON_CHANGE", True)
    published = await _published_answer(store, editorial, client)
    aid = published["id"]

    # Amended: matn o'zgardi
    changed = _lex_article("law_test_art_1", "Nogironligi bo'lgan shaxslarga oshirilgan nafaqa to'lanadi.")
    changed.metadata.source_hash = changed.calculate_source_hash()
    store.fts_store.upsert_article(changed)
    res = check_legal_links(store, editorial)
    assert res["new_notifications"] == 1
    items, _ = editorial.list_notifications(status="open")
    assert items[0]["kind"] == "norm_amended"
    assert items[0]["old_text"] != items[0]["new_text"]
    assert editorial.get_answer(aid)["status"] == "needs_review"
    assert store.get_article(f"qa_{aid}") is None  # qidiruvdan olindi
    # Takrorlanmaslik: ikkinchi tekshiruv yangi bildirishnoma yaratmaydi
    res2 = check_legal_links(store, editorial)
    assert res2["new_notifications"] == 0

    # Repealed
    rep = store.get_article("law_test_art_1")
    rep2 = rep.model_copy(deep=True)
    rep2.metadata.status = ArticleStatus.REPEALED
    store.fts_store.upsert_article(rep2)
    res3 = check_legal_links(store, editorial)
    all_open, _ = editorial.list_notifications(status="all")
    assert "norm_repealed" in {n["kind"] for n in all_open}

    # Removed: modda butunlay o'chirilgan
    store.delete_article("law_test_art_1")
    res4 = check_legal_links(store, editorial)
    all_open, _ = editorial.list_notifications(status="all")
    assert "norm_removed" in {n["kind"] for n in all_open}
    assert res3["checked_links"] >= 1 and res4["checked_links"] >= 1


# -- 6. Resolve: 4 harakat --------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resolve_keep(store, editorial, client):
    published = await _published_answer(store, editorial, client)
    aid = published["id"]
    changed = _lex_article("law_test_art_1", "O'zgargan yangi matn hujjatda.")
    changed.metadata.source_hash = changed.calculate_source_hash()
    store.fts_store.upsert_article(changed)
    check_legal_links(store, editorial)
    notif, _ = editorial.list_notifications(status="open")
    notif = notif[0]
    result = svc.resolve_notification_action(store, editorial, notif, action="keep", note="hali to'g'ri")
    assert result["status"] == "resolved"
    links = editorial.list_links(owner_type="curated", owner_id=str(aid))
    assert links[0]["snapshot_hash"] == changed.metadata.source_hash
    assert editorial.get_answer(aid)["status"] == "published"


@pytest.mark.asyncio
async def test_resolve_edited_unpublish_delete(store, editorial, client):
    # edited
    published = await _published_answer(store, editorial, client, question="Tahrirlanadigan savol?")
    aid = published["id"]
    changed = _lex_article("law_test_art_1", "Yana o'zgargan matn.")
    changed.metadata.source_hash = changed.calculate_source_hash()
    store.fts_store.upsert_article(changed)
    check_legal_links(store, editorial)
    notif = editorial.list_notifications(status="open")[0][0]
    editorial.update_answer(aid, {"answer_md": "Yangilangan javob matni, tahrirlandi."}, editor="t", action="edit")
    result = svc.resolve_notification_action(store, editorial, notif, action="edited", note="tahrirlandi")
    assert result["status"] == "resolved"
    assert editorial.get_answer(aid)["status"] == "published"

    # unpublish
    published2 = await _published_answer(store, editorial, client, question="Olinadigan savol matni?")
    aid2 = published2["id"]
    changed2 = _lex_article("law_test_art_1", "Uchinchi o'zgarish matni.")
    changed2.metadata.source_hash = changed2.calculate_source_hash()
    store.fts_store.upsert_article(changed2)
    check_legal_links(store, editorial)
    notif2 = [n for n in editorial.list_notifications(status="open")[0] if n["owner_id"] == str(aid2)][0]
    svc.resolve_notification_action(store, editorial, notif2, action="unpublish", note="vaqtincha")
    assert editorial.get_answer(aid2)["status"] == "archived"

    # delete
    published3 = await _published_answer(store, editorial, client, question="O'chiriladigan savol matni?")
    aid3 = published3["id"]
    changed3 = _lex_article("law_test_art_1", "To'rtinchi o'zgarish matni.")
    changed3.metadata.source_hash = changed3.calculate_source_hash()
    store.fts_store.upsert_article(changed3)
    check_legal_links(store, editorial)
    notif3 = [n for n in editorial.list_notifications(status="open")[0] if n["owner_id"] == str(aid3)][0]
    svc.resolve_notification_action(store, editorial, notif3, action="delete", note="eski")
    assert editorial.get_answer(aid3) is None


# -- 7. Admin endpointlar: auth + CRUD ---------------------------------------------------------------------
def test_admin_endpoints_require_admin():
    from fastapi.testclient import TestClient
    from src.api.app import app
    with TestClient(app) as c:
        r = c.get("/api/v1/admin/editorial/notifications/count",
                  headers={"X-Forwarded-For": "203.0.113.7"})
        assert r.status_code == 401
        r2 = c.get("/api/v1/admin/editorial/notifications/count",
                   headers={"X-Forwarded-For": "203.0.113.7", "X-Admin-Key": "wrong"})
        assert r2.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_crud_endpoints(store, editorial, client, monkeypatch):
    import src.editorial.router as router_mod
    monkeypatch.setattr(router_mod, "_get_store", lambda: store)
    monkeypatch.setattr(router_mod, "_get_editorial", lambda: editorial)
    from fastapi.testclient import TestClient
    from src.api.app import app
    await _seed_lex(store, client)
    with TestClient(app) as c:
        r = c.post("/api/v1/admin/editorial/answers", json={
            "question": "Endpoint orqali savol matni?",
            "answer_md": "Endpoint orqali javob matni uzun.",
        })
        assert r.status_code == 200, r.text
        aid = r.json()["id"]

        # Qisqa savol -> 422
        r_bad = c.post("/api/v1/admin/editorial/answers", json={"question": "x", "answer_md": "y" * 50})
        assert r_bad.status_code == 422

        # Noto'g'ri modda -> 404; nashr asosiz -> 409
        assert c.post(f"/api/v1/admin/editorial/answers/{aid}/links",
                      json={"canonical_id": "missing_id"}).status_code == 404
        assert c.post(f"/api/v1/admin/editorial/answers/{aid}/publish").status_code == 409

        # Bog'lash + nashr
        r_link = c.post(f"/api/v1/admin/editorial/answers/{aid}/links",
                        json={"canonical_id": "law_test_art_1"})
        assert r_link.status_code == 200, r_link.text
        r_pub = c.post(f"/api/v1/admin/editorial/answers/{aid}/publish")
        assert r_pub.status_code == 200, r_pub.text
        assert store.get_article(f"qa_{aid}") is not None

        # Ro'yxat filtri + pagination
        r_list = c.get("/api/v1/admin/editorial/answers?status=published&limit=10&offset=0")
        assert r_list.status_code == 200 and r_list.json()["total"] >= 1

        # Norms search + laws
        assert c.get("/api/v1/admin/editorial/norms/search?q=nafaqa").status_code == 200
        assert c.get("/api/v1/admin/editorial/laws").status_code == 200

        # Watch orqali bildirishnoma, keyin resolve keep
        changed = _lex_article("law_test_art_1", "Endpoint testida o'zgargan matn.")
        changed.metadata.source_hash = changed.calculate_source_hash()
        store.fts_store.upsert_article(changed)
        r_check = c.post("/api/v1/admin/editorial/check-links")
        assert r_check.status_code == 200 and r_check.json()["new_notifications"] >= 1
        r_notifs = c.get("/api/v1/admin/editorial/notifications?status=open")
        assert r_notifs.status_code == 200 and r_notifs.json()["total"] >= 1
        nid = r_notifs.json()["items"][0]["id"]
        r_res = c.post(f"/api/v1/admin/editorial/notifications/{nid}/resolve",
                       json={"action": "keep", "note": "tekshirildi"})
        assert r_res.status_code == 200, r_res.text


# -- 8. Refresh diff mantiqi (tarmoq mock) ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_refresh_diff_logic(store, client):
    art = await _seed_lex(store, client)
    old_hash = art.metadata.source_hash
    # O'zgarmagan — diff yo'q
    same = store.get_article(art.canonical_id)
    assert same.metadata.source_hash == old_hash
    # O'zgargan — faqat shu upsert qilinadi
    changed = copy.deepcopy(art).model_copy(deep=True)
    changed.translations["uz"] = "Mutlaqo yangi tahrirdagi matn."
    changed.metadata.source_hash = changed.calculate_source_hash()
    assert changed.metadata.source_hash != old_hash
    await store.index_article(changed, client=client)
    assert store.get_article(art.canonical_id).get_text("uz") == "Mutlaqo yangi tahrirdagi matn."
    # Yo'qolgan — o'chiriladi
    store.delete_article(art.canonical_id)
    assert store.get_article(art.canonical_id) is None
    # Kuchini yo'qotgan — belgilanadi
    rep = _lex_article(art.canonical_id, "Eski matn.", status="repealed")
    rep.metadata.source_hash = rep.calculate_source_hash()
    await store.index_article(rep, client=client)
    assert store.get_article(art.canonical_id).metadata.status == ArticleStatus.REPEALED


def test_refresh_cli_options():
    import subprocess, sys
    p = subprocess.run([sys.executable, "scripts/build_disability_corpus.py", "refresh", "--help"],
                       capture_output=True, text=True)
    assert p.returncode == 0
    assert "--limit" in p.stdout and "--law-ids" in p.stdout


# -- 9. Generatsiyada curated ustuvorligi --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_curated_priority_and_generation(store, editorial, client):
    from src.editorial.retrieval import ensure_curated_contexts
    from src.generation.generator import AnswerGenerator, _has_curated_context
    from src.retrieval.reranker import RetrievedArticleContext

    published = await _published_answer(store, editorial, client, question="Nafaqa kimga to'lanadi?")
    qa = store.get_article(f"qa_{published['id']}")
    other = await _seed_lex(store, client, cid="law_test_art_2", text="Boshqa modda matni.")
    # the reranker ranked the curated answer second; it moves to the front and its basis is added
    base = [RetrievedArticleContext(article=other, final_score=0.6, source_tag="rrf", rerank_score=0.9),
            RetrievedArticleContext(article=qa, final_score=0.5, source_tag="rrf", rerank_score=0.92)]
    merged = ensure_curated_contexts(base, store, editorial, min_rerank_score=0.7)
    ids = [c.article.canonical_id for c in merged]
    assert ids == [f"qa_{published['id']}", "law_test_art_1", "law_test_art_2"]
    assert merged[1].rerank_score is None          # an added basis cannot lift the relevance gate by itself
    assert _has_curated_context(merged)

    gen = AnswerGenerator(client=client)
    result = await gen.generate_answer(
        query="Nafaqa kimga to'lanadi?", contexts=merged, language="uz", mode="plain")
    assert result.answer and len(result.answer.strip()) > 0
    assert any(c.source_type in ("curated", "lex") for c in result.citations)


def test_validator_curated_and_lex():
    from src.generation.validator import CitationValidator
    from src.retrieval.reranker import RetrievedArticleContext
    qa = _lex_article("qa_1", "Huquqshunos javobi matni.", source_type="curated")
    qa.metadata.source_hash = qa.calculate_source_hash()
    lex = _lex_article("law_test_art_1", "Qonun matni shu yerda.")
    lex.metadata.source_hash = lex.calculate_source_hash()
    ctxs = [RetrievedArticleContext(article=qa, final_score=1.0, source_tag="curated"),
            RetrievedArticleContext(article=lex, final_score=0.9, source_tag="legal_basis")]
    res = CitationValidator.validate_and_sanitize(
        "Javob matni [qa_1][law_test_art_1]", retrieved_contexts=ctxs, language="uz")
    by_id = {c.canonical_id: c.source_type for c in res.resolved_citations}
    assert by_id == {"qa_1": "curated", "law_test_art_1": "lex"}

    only_qa = CitationValidator.validate_and_sanitize(
        "Javob matni [qa_1]", retrieved_contexts=ctxs[:1], language="uz")
    assert any("curated_without_lex_basis" in w for w in only_qa.warnings)


# -- 10. Regressions found in review ---------------------------------------------------------------------------
def _amend(store, text, cid="law_test_art_1"):
    art = _lex_article(cid, text)
    art.metadata.source_hash = art.calculate_source_hash()
    store.fts_store.upsert_article(art)
    return art


@pytest.mark.asyncio
async def test_weak_or_unpublished_curated_hits_are_not_served(store, editorial, client):
    from src.editorial.retrieval import ensure_curated_contexts
    from src.retrieval.reranker import RetrievedArticleContext

    published = await _published_answer(store, editorial, client)
    qa = store.get_article(f"qa_{published['id']}")
    lex = store.get_article("law_test_art_1")
    weak = [RetrievedArticleContext(article=lex, final_score=0.6, source_tag="rrf", rerank_score=0.9),
            RetrievedArticleContext(article=qa, final_score=0.5, source_tag="rrf", rerank_score=0.4)]
    # a loosely related curated answer must not be presented as "the" answer
    assert [c.article.canonical_id for c in ensure_curated_contexts(weak, store, editorial, 0.7)] == ["law_test_art_1"]

    # without model scores only a top hit counts
    unscored = [RetrievedArticleContext(article=qa, final_score=0.5, source_tag="rrf")]
    assert ensure_curated_contexts(unscored, store, editorial, 0.7)[0].article.canonical_id == qa.canonical_id

    # a lingering projection of an answer that is no longer published is never served
    editorial.update_answer(published["id"], {"status": "needs_review"})
    strong = [RetrievedArticleContext(article=qa, final_score=0.5, source_tag="rrf", rerank_score=0.99)]
    assert ensure_curated_contexts(strong, store, editorial, 0.7) == []


@pytest.mark.asyncio
async def test_answer_stays_suspended_until_every_change_is_reviewed(store, editorial, client):
    published = await _published_answer(store, editorial, client)
    aid = published["id"]
    second = await _seed_lex(store, client, cid="law_test_art_2", text="Ikkinchi asos matni.")
    text, h, st = svc.snapshot_of(second)
    editorial.add_link(owner_type="curated", owner_id=str(aid), canonical_id="law_test_art_2", law_id="law_test",
                       article_label="O'RQ-999 2-modda", snapshot_text=text, snapshot_hash=h, snapshot_status=st)
    _amend(store, "Birinchi asos o'zgardi.")
    _amend(store, "Ikkinchi asos ham o'zgardi.", cid="law_test_art_2")
    assert check_legal_links(store, editorial)["new_notifications"] == 2
    first, other = editorial.list_notifications(status="open")[0]

    svc.resolve_notification_action(store, editorial, first, action="keep")
    assert editorial.get_answer(aid)["status"] == "needs_review"      # the other change is still unreviewed
    with pytest.raises(ValueError, match="open_notifications"):
        await svc.publish_answer(store, editorial, aid)

    await svc.resolve_notification(store, editorial, other, action="keep")
    assert editorial.get_answer(aid)["status"] == "published"
    assert store.get_article(f"qa_{aid}") is not None          # back in search


@pytest.mark.asyncio
async def test_keep_is_refused_for_a_repealed_or_removed_norm(store, editorial, client):
    published = await _published_answer(store, editorial, client)
    aid = published["id"]
    store.delete_article("law_test_art_1")
    check_legal_links(store, editorial)
    notif = editorial.list_notifications(status="open")[0][0]
    assert notif["kind"] == "norm_removed"
    with pytest.raises(ValueError, match="kuchini yo'qotgan"):
        svc.resolve_notification_action(store, editorial, notif, action="keep")
    assert editorial.get_answer(aid)["status"] == "needs_review"

    # the editor replaces the basis, then marks the card as handled
    replacement = await _seed_lex(store, client, cid="law_test_art_3", text="Amaldagi yangi modda.")
    text, h, st = svc.snapshot_of(replacement)
    editorial.remove_link(owner_type="curated", owner_id=str(aid), canonical_id="law_test_art_1")
    editorial.add_link(owner_type="curated", owner_id=str(aid), canonical_id="law_test_art_3", law_id="law_test",
                       article_label="O'RQ-999 3-modda", snapshot_text=text, snapshot_hash=h, snapshot_status=st)
    svc.resolve_notification_action(store, editorial, notif, action="edited")
    assert editorial.get_answer(aid)["status"] == "published"


@pytest.mark.asyncio
async def test_renotify_when_a_norm_returns_to_an_earlier_wording(store, editorial, client):
    await _published_answer(store, editorial, client)
    original = store.get_article("law_test_art_1").get_text("uz")
    for wording in ("B tahriri.", original, "B tahriri."):
        _amend(store, wording)
        assert check_legal_links(store, editorial)["new_notifications"] == 1
        notif = editorial.list_notifications(status="open")[0][0]
        svc.resolve_notification_action(store, editorial, notif, action="keep")


@pytest.mark.asyncio
async def test_open_card_shows_the_latest_wording(store, editorial, client):
    await _published_answer(store, editorial, client)
    _amend(store, "Birinchi o'zgarish.")
    check_legal_links(store, editorial)
    _amend(store, "Ikkinchi o'zgarish.")
    assert check_legal_links(store, editorial)["new_notifications"] == 0
    cards = editorial.list_notifications(status="open")[0]
    assert len(cards) == 1 and cards[0]["new_text"] == "Ikkinchi o'zgarish."


@pytest.mark.asyncio
async def test_unpublished_on_change_is_not_renotified_and_needs_relink(store, editorial, client):
    published = await _published_answer(store, editorial, client)
    aid = published["id"]
    _amend(store, "O'zgargan matn.")
    check_legal_links(store, editorial)
    notif = editorial.list_notifications(status="open")[0][0]
    svc.resolve_notification_action(store, editorial, notif, action="unpublish")
    assert check_legal_links(store, editorial)["new_notifications"] == 0
    with pytest.raises(ValueError, match="link_stale"):
        await svc.publish_answer(store, editorial, aid)
    # re-linking after reading the new text refreshes the snapshot
    art = store.get_article("law_test_art_1")
    text, h, st = svc.snapshot_of(art)
    editorial.add_link(owner_type="curated", owner_id=str(aid), canonical_id="law_test_art_1", law_id="law_test",
                       article_label="O'RQ-999 1-modda", snapshot_text=text, snapshot_hash=h, snapshot_status=st)
    assert (await svc.publish_answer(store, editorial, aid))["status"] == "published"


@pytest.mark.asyncio
async def test_deleting_an_answer_closes_its_notifications(store, editorial, client):
    published = await _published_answer(store, editorial, client)
    _amend(store, "O'zgargan matn.")
    check_legal_links(store, editorial)
    assert editorial.count_open_notifications() == 1
    editorial.delete_answer(published["id"])
    assert editorial.count_open_notifications() == 0
