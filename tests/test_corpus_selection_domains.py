"""Corpus selection by life domain: whole social-assistance acts, curated domain acts, widened links re-based."""
import importlib.util
import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

_spec = importlib.util.spec_from_file_location(
    "build_disability_corpus", Path(__file__).resolve().parents[1] / "scripts" / "build_disability_corpus.py")
corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(corpus)


def test_keep_whole_social_acts_and_cited_acts_but_not_codes_or_long_acts():
    social = "“Temir daftar” orqali ijtimoiy xizmat va yordam koʻrsatish tartibi toʻgʻrisida"
    assert corpus._keep_whole(social, 91, "VMQ", tier=1)
    assert not corpus._keep_whole(social, 91, "VMQ", tier=2)                     # tier 2 needs a citation
    assert not corpus._keep_whole("Terrorizmga qarshi kurash toʻgʻrisida", 30, "Qonun", tier=1)
    assert not corpus._keep_whole("Oʻzbekiston Respublikasining Mehnat kodeksi", 593, "Kodeks", tier=1)
    assert not corpus._keep_whole(social, 301, "VMQ", tier=1)
    # editors cite it: kept when social, or when cited twice and short
    assert corpus._keep_whole("Davlat boji toʻgʻrisida", 33, "Qonun", tier=2, cited_posts=2)
    assert not corpus._keep_whole("Temir yoʻl transportida yoʻlovchilar tashish qoidalari", 239, "VMQ", tier=2, cited_posts=3)
    assert not corpus._keep_whole("Ichki ishlar organlari toʻgʻrisida", 53, "Qonun", tier=2, cited_posts=1)


def test_domain_command_adds_accepted_acts_and_respects_curator(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "SOURCES", tmp_path)
    (tmp_path / "disability_registry.json").write_text(json.dumps({"documents": [{"lex_id": "-1", "title": "bor"}]}))
    cand = lambda lex, dec="include", status="active", units=10: {  # noqa: E731
        "lex_id": lex, "number": f"N{lex}", "title": f"T{lex}", "doc_type": "Qonun", "adopted": "2020-01-01",
        "status": status, "units": units, "decision": dec, "domain": "d", "reason": "r"}
    (tmp_path / "domain_candidates.json").write_text(json.dumps({"candidates": [
        cand("-1"), cand("-2"), cand("-3", dec="skip"), cand("-4", status="repealed"), cand("-5"), cand("-6"),
        cand("-7", units=0)]}))
    (tmp_path / "domain_overrides.json").write_text(json.dumps({"skip": {"-5": "aloqasiz"}, "partial": {"-6": "tor"}}))

    corpus.cmd_domain(Namespace(apply=True))

    docs = json.loads((tmp_path / "disability_registry.json").read_text())["documents"]
    added = {d["lex_id"]: d for d in docs if d.get("source") == "domain_review"}
    assert set(added) == {"-2", "-6"}                     # already present, skipped, repealed, empty: not added
    assert added["-2"]["include"] == "all" and added["-6"]["include"] == "disability_articles"
    corpus.cmd_domain(Namespace(apply=True))              # idempotent
    assert len(json.loads((tmp_path / "disability_registry.json").read_text())["documents"]) == 3


def test_rebaseline_only_links_whose_units_just_grew(monkeypatch):
    from src.editorial import doc_watch

    units = {"a": ("h1", "active", "1"), "b": ("h2", "active", "2"), "c": ("h3", "active", "3")}
    monkeypatch.setattr(doc_watch, "law_units", lambda store, law_id: units)
    grown = json.dumps({"a": "h1|active", "b": "h2|active"})            # c was added by the wider selection
    changed = json.dumps({"a": "OLD|active", "b": "h2|active"})         # a was amended on Lex.uz
    links = [
        {"id": 1, "canonical_id": "law:x", "owner_type": "huquqplus", "owner_id": "uz:1", "snapshot_text": grown, "snapshot_hash": "s1"},
        {"id": 2, "canonical_id": "law:x", "owner_type": "huquqplus", "owner_id": "uz:2", "snapshot_text": changed, "snapshot_hash": "s2"},
        {"id": 3, "canonical_id": "law:y", "owner_type": "huquqplus", "owner_id": "uz:3", "snapshot_text": grown, "snapshot_hash": "s3"},
    ]
    calls = []
    editorial = SimpleNamespace(
        list_all_links=lambda: links,
        refresh_link_snapshot=lambda link_id, **kw: calls.append(("snap", link_id)),
        resolve_open_for_owner_link=lambda **kw: calls.append(("resolve", kw["owner_id"], kw["resolution"])),
    )
    assert doc_watch.rebaseline_widened(None, editorial, {"x"}) == 1
    assert calls == [("snap", 1), ("resolve", "uz:1", "corpus_widened")]   # amended link and other act untouched


def test_lex_link_fragment_with_encoded_junk_resolves_to_element_id():
    from src.ingestion.huquqplus_client import lex_element_id, parse_lex_ref

    assert parse_lex_ref("https://lex.uz/docs/-5049511#-5054422%20").element_id == "-5054422"
    assert lex_element_id("#-5054422 ") == "-5054422"
    assert lex_element_id("") is None and lex_element_id("top") is None
    assert parse_lex_ref("https://lex.uz/docs/-5049511").element_id is None


def test_partial_code_keeps_listed_chapters_besides_disability_units():
    from src.ingestion.corpus_builder import CorpusBuilder, SourceSpec
    from src.ingestion.lex_structured import LexDocument, LexUnit

    doc = LexDocument(doc_id="-1", url="https://lex.uz/docs/-1", title="Fuqarolik kodeksi (ikkinchi qism)", units=[
        LexUnit(kind="article", number="914", chapter="52-bob. Sug'urta", text="Sug'urta shartnomasi yozma shaklda tuziladi."),
        LexUnit(kind="article", number="1141", chapter="68-bob. Qonun bo'yicha vorislik",
                text="Merosdagi majburiy ulush mehnatga layoqatsiz vorislarga beriladi."),
        LexUnit(kind="article", number="1180", chapter="166-bob. Boshqa", text="Boshqa qoida bu yerda yozilgan."),
        LexUnit(kind="article", number="1009", chapter="57-bob. Zarar", text="Nogironligi bo'lgan shaxsga yetkazilgan zarar qoplanadi."),
    ])
    spec = SourceSpec(lex_id="-1", law_id="cc2", include="disability_articles", chapters=["66-bob.", "68-bob."])
    arts, _ = CorpusBuilder(today="2026-10-13").to_articles(doc, spec)
    assert sorted(a.metadata.article_number for a in arts) == ["1009-modda", "1141-modda"]
    # without chapters only the unit that mentions disability is kept
    arts, _ = CorpusBuilder(today="2026-10-13").to_articles(doc, SourceSpec(lex_id="-1", law_id="cc2", include="disability_articles"))
    assert [a.metadata.article_number for a in arts] == ["1009-modda"]
