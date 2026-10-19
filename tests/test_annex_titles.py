"""metadata.annex_title: Lex.uz ilova bandlari qaysi ro'yxatning elementi ekanini ko'rsatadi."""
import argparse
import hashlib
import json

from scripts.build_disability_corpus import cmd_annex_titles
from src.generation.prompts import format_context_for_llm
from src.ingestion.corpus_builder import CorpusBuilder, SourceSpec
from src.ingestion.lex_structured import LexDocument, LexUnit
from src.nlp.transliteration import normalize_apostrophes
from src.retrieval.reranker import RetrievedArticleContext
from src.storage.hybrid_store import HybridStore

ANNEX = "Tibbiyot muassasalarida ovqatlanish to'lovidan ozod qilinadigan shaxslar (bemorlar) toifalari"


def _builder() -> CorpusBuilder:
    builder = CorpusBuilder.__new__(CorpusBuilder)  # to_articles needs no network client
    builder.today = "2026-10-13"
    return builder


def _doc(annex_title: str = "") -> LexDocument:
    return LexDocument(
        doc_id="123",
        url="https://lex.uz/uz/docs/123",
        title="Test qarori",
        number="VMQ-31",
        doc_type="VMQ",
        body="Vazirlar Mahkamasi",
        adopted_date="2016-01-01",
        effective_date="2016-01-02",
        units=[
            LexUnit(kind="article", number="1", title="Umumiy qoida",
                    text="Umumiy qoida matni.", element_ids=["e1"]),
            LexUnit(kind="clause", number="1", title="", text="I va II guruh nogironligi bo'lgan shaxslar.",
                    annex_number="2", annex_title=annex_title, element_ids=["e2"]),
        ],
    )


def _spec() -> SourceSpec:
    return SourceSpec(lex_id="123", law_id="vmq_test_2016", number="VMQ-31", tier=1, include="all")


def _ctx(article, score: float = 1.0) -> RetrievedArticleContext:
    return RetrievedArticleContext(article=article, final_score=score, source_tag="test")


def test_builder_keeps_annex_title_and_stable_hash():
    builder = _builder()  # to_articles needs no client
    arts, _rep = builder.to_articles(_doc(ANNEX), _spec(), None)
    by_id = {a.canonical_id: a for a in arts}
    annex = by_id["vmq_test_2016_a2_p_1"]
    plain = by_id["vmq_test_2016_art_1"]
    assert annex.metadata.annex_title == normalize_apostrophes(ANNEX)
    assert plain.metadata.annex_title is None
    # source_hash, canonical_id and text are computed exactly as before (refresh must not see a change)
    assert annex.metadata.source_hash == "sha256:" + hashlib.sha256(
        "I va II guruh nogironligi bo'lgan shaxslar.".encode("utf-8")).hexdigest()
    assert annex.translations == {"uz": "I va II guruh nogironligi bo'lgan shaxslar."}
    assert ANNEX.split(" ")[0][:8] in annex.to_fts_document("uz")


def test_format_context_shows_annex_title():
    builder = _builder()
    arts, _rep = builder.to_articles(_doc(ANNEX), _spec(), None)
    by_id = {a.canonical_id: a for a in arts}
    out = format_context_for_llm([_ctx(by_id["vmq_test_2016_a2_p_1"])])
    assert ("List/annex title (this unit is an item of this list; it applies only within it): "
            + normalize_apostrophes(ANNEX)) in out
    out_plain = format_context_for_llm([_ctx(by_id["vmq_test_2016_art_1"])])
    assert "List/annex title" not in out_plain


def test_annex_titles_apply_updates_only_annex_title(tmp_path, monkeypatch, capsys):
    import scripts.build_disability_corpus as mod

    builder = _builder()
    old_arts, _rep = builder.to_articles(_doc(""), _spec(), None)  # store as built before the change
    store = HybridStore(str(tmp_path / "store"))
    for a in old_arts:
        store.fts_store.upsert_article(a)
    before = {a.canonical_id: store.fts_store.get_article(a.canonical_id) for a in old_arts}
    before_dump = {cid: a.model_dump_json() for cid, a in before.items()}

    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"documents": [{
        "lex_id": "123", "law_id": "vmq_test_2016", "number": "VMQ-31", "title": "Test qarori",
        "tier": 1, "include": "all",
    }]}), encoding="utf-8")
    monkeypatch.setattr(mod, "_read_cached_html", lambda raw_dir, lex_id: "<html/>")
    monkeypatch.setattr(mod.LexDocumentParser, "parse",
                        lambda self, html, doc_id, language="uz": _doc(ANNEX))
    args = argparse.Namespace(store_dir=str(tmp_path / "store"), apply=True,
                              registry_file=str(reg), raw_dir=str(tmp_path / "raw"), limit=None)
    cmd_annex_titles(args)
    out = capsys.readouterr().out
    assert "annex-titles: 1 docs, 1 units updated, 0 docs without cache" in out

    assert store.count() == len(old_arts)  # nothing added or removed
    store.fts_store._article_cache.clear()  # the command wrote via its own store handle
    after_annex = store.fts_store.get_article("vmq_test_2016_a2_p_1")
    assert after_annex.metadata.annex_title == normalize_apostrophes(ANNEX)
    assert after_annex.translations == before["vmq_test_2016_a2_p_1"].translations
    assert after_annex.metadata.source_hash == before["vmq_test_2016_a2_p_1"].metadata.source_hash
    assert after_annex.metadata.status == before["vmq_test_2016_a2_p_1"].metadata.status
    # only metadata.annex_title changed in the stored JSON
    assert (json.loads(after_annex.model_dump_json())["metadata"]["annex_title"]
            == normalize_apostrophes(ANNEX))
    before_meta = json.loads(before_dump["vmq_test_2016_a2_p_1"])["metadata"]
    after_meta = json.loads(after_annex.model_dump_json())["metadata"]
    assert {k: v for k, v in before_meta.items() if k != "annex_title"} == \
        {k: v for k, v in after_meta.items() if k != "annex_title"}
    after_plain = store.fts_store.get_article("vmq_test_2016_art_1")
    assert after_plain.metadata.annex_title is None
    assert after_plain.model_dump_json() == before_dump["vmq_test_2016_art_1"]
