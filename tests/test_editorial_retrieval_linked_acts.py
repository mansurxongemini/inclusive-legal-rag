"""Whole-act Lex.uz links of a Huquq+ article bring the matching units of that act into the context."""
from types import SimpleNamespace

from src.config import settings
from src.editorial.retrieval import add_linked_act_units, ensure_curated_contexts
from src.retrieval.reranker import RetrievedArticleContext
from src.schema.canonical import ArticleStatus


class _Art:
    def __init__(self, cid, text, status=ArticleStatus.ACTIVE, cross_references=None):
        self.canonical_id = cid
        self.metadata = SimpleNamespace(
            status=status,
            cross_references=cross_references or [],
        )
        self._text = text

    def get_text(self, lang):
        return self._text


def _ctx(art, rerank_score=None, source_tag="primary", final_score=0.9):
    return RetrievedArticleContext.model_construct(
        article=art,
        final_score=final_score,
        source_tag=source_tag,
        rerank_score=rerank_score,
    )


def test_matching_units_of_whole_act_link_follow_the_article(monkeypatch):
    units = {
        "vmq_313_2024_a1_p_6": _Art("vmq_313_2024_a1_p_6", "Yordam oluvchilar vaucher asosida oziq-ovqat, kiyim-kechak tovarlarni oladi"),
        "vmq_313_2024_a1_p_7": _Art("vmq_313_2024_a1_p_7", "Jamg'arma budjet mablag'lari hisobidan shakllantiriladi"),
        "vmq_313_2024_a1_p_9": _Art("vmq_313_2024_a1_p_9", "vaucher oziq-ovqat kiyim-kechak", status=ArticleStatus.REPEALED),
    }
    import src.editorial.doc_watch as dw
    import src.editorial.retrieval as er
    # the fake articles are not CanonicalArticle models: build the contexts without validation
    monkeypatch.setattr(er, "RetrievedArticleContext",
                        type("Ctx", (), {"__new__": lambda cls, **kw: RetrievedArticleContext.model_construct(**kw)}))
    monkeypatch.setattr(dw, "law_units", lambda store, law_id: {cid: ("h", "active", cid) for cid in units})
    store = SimpleNamespace(get_articles_batch=lambda ids: {i: units[i] for i in ids})
    editorial = SimpleNamespace(list_links=lambda owner_type, owner_id: [
        {"canonical_id": "law:vmq_313_2024"}, {"canonical_id": "vmq_1_art_2"}])
    hp = _ctx(_Art("hp_uz_5862_2", "maqola"), rerank_score=0.9)
    other = _ctx(_Art("pq_267_2024_p_2", "boshqa"), rerank_score=None)

    # When no picks exist, linked acts follow the article before unscored contexts as before
    out = add_linked_act_units([hp, other], store, editorial,
                               "Oziq-ovqat, kiyim-kechakni vaucher yoki kartamga olsam bo'ladimi?")
    ids = [c.article.canonical_id for c in out]
    assert ids == ["hp_uz_5862_2", "vmq_313_2024_a1_p_6", "pq_267_2024_p_2"]   # unrelated and repealed units stay out
    assert out[1].source_tag == "legal_basis"


def test_picks_stand_before_hp_basis_in_ensure_curated_contexts(monkeypatch):
    import src.editorial.retrieval as er

    monkeypatch.setattr(er, "RetrievedArticleContext",
                        type("Ctx", (), {"__new__": lambda cls, **kw: RetrievedArticleContext.model_construct(**kw)}))

    ref = SimpleNamespace(target_canonical_id="law_ref_1")
    ref_art = _Art("law_ref_1", "asos matni")
    hp = _ctx(_Art("hp_uz_100_1", "hp matni", cross_references=[ref]), rerank_score=0.85)

    pick = _ctx(_Art("law_pick_1", "pick matni"), rerank_score=0.50)  # >= RERANK_PICK_MIN
    other = _ctx(_Art("law_other_1", "other matni"), rerank_score=0.01)  # < RERANK_PICK_MIN

    monkeypatch.setattr(er, "_get_hp_post_status", lambda lang, wp_id: "active")
    store = SimpleNamespace(get_article=lambda cid: ref_art if cid == "law_ref_1" else None)
    editorial = SimpleNamespace(open_notifications_for_owner=lambda **kw: [])

    contexts = [hp, pick, other]
    out = ensure_curated_contexts(contexts, store, editorial)
    ids = [c.article.canonical_id for c in out]
    # Ordering: hp_primary -> picks -> hp_basis -> others
    assert ids == ["hp_uz_100_1", "law_pick_1", "law_ref_1", "law_other_1"]


def test_picks_stand_before_linked_acts_in_add_linked_act_units(monkeypatch):
    units = {
        "vmq_313_2024_a1_p_6": _Art("vmq_313_2024_a1_p_6", "vaucher oziq-ovqat yordam"),
    }
    import src.editorial.doc_watch as dw
    import src.editorial.retrieval as er

    monkeypatch.setattr(er, "RetrievedArticleContext",
                        type("Ctx", (), {"__new__": lambda cls, **kw: RetrievedArticleContext.model_construct(**kw)}))
    monkeypatch.setattr(dw, "law_units", lambda store, law_id: {cid: ("h", "active", cid) for cid in units})
    store = SimpleNamespace(get_articles_batch=lambda ids: {i: units[i] for i in ids})
    editorial = SimpleNamespace(list_links=lambda owner_type, owner_id: [
        {"canonical_id": "law:vmq_313_2024"}])

    hp = _ctx(_Art("hp_uz_5862_2", "maqola"), rerank_score=0.9)
    pick = _ctx(_Art("law_pick_modda_1", "muhim qonun"), rerank_score=0.7)  # pick >= RERANK_PICK_MIN
    low = _ctx(_Art("law_low_modda_9", "past balli qonun"), rerank_score=0.01)  # low < RERANK_PICK_MIN

    out = add_linked_act_units([hp, pick, low], store, editorial, "vaucher oziq-ovqat")
    ids = [c.article.canonical_id for c in out]
    # pick stands before linked act units, linked units stand before low/unscored
    assert ids == ["hp_uz_5862_2", "law_pick_modda_1", "vmq_313_2024_a1_p_6", "law_low_modda_9"]


def test_no_hp_context_leaves_contexts_unchanged():
    lex = _ctx(_Art("law_disability_2020_art_15", "matn"))
    editorial = SimpleNamespace(list_links=lambda **kw: [])
    assert add_linked_act_units([lex], SimpleNamespace(), editorial, "nafaqa qancha") == [lex]
