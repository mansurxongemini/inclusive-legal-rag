"""Full-text query building: whole words, quoted and stripped of FTS syntax, codes kept whole."""

from src.config import settings
from src.schema.canonical import CanonicalArticle
from src.storage.fts_store import SqliteFtsStore, build_fts_terms


def test_whole_words_are_quoted_prefix_terms_in_question_order():
    assert build_fts_terms("Nogironligi bo'lgan bolaga qanday nafaqa") == ['"Nogironligi"*', '"bolgan"*', '"bolaga"*', '"qanday"*', '"nafaqa"*']
    assert build_fts_terms("nafaqa nafaqa") == ['"nafaqa"*']                         # a repeated word is searched once


def test_codes_stay_whole_and_syntax_characters_are_stripped():
    assert build_fts_terms("483-modda VMQ-62") == ['"483-modda"*', '"VMQ-62"*']
    # a question cannot inject an FTS5 operator or a column filter: every word is quoted, quotes and symbols are dropped
    assert build_fts_terms('foo" OR "bar') == ['"foo"*', '"OR"*', '"bar"*']
    assert build_fts_terms("title:nafaqa NEAR(a b) *") == ['"titlenafaqa"*', '"NEARa"*', '"b"*']
    assert build_fts_terms("?!") == []


def _article(cid, text, title="Qoida"):
    return CanonicalArticle(
        canonical_id=cid,
        metadata={"law_id": "t", "law_title": {"uz": "Sinov"}, "law_number": "Q-1", "article_number": "1-modda",
                  "article_title": {"uz": title}, "source_url": "https://lex.uz/docs/1", "effective_date": "2024-01-01",
                  "last_verified_date": "2026-10-01", "source_hash": "sha256:x", "category": "social_protection"},
        translations={"uz": text},
    )


def test_a_unit_is_found_by_the_words_it_contains(tmp_path):
    store = SqliteFtsStore(str(tmp_path / "t.db"))
    store.upsert_article(_article("t_art_1", "Nogironlik pensiyasi har oyda to'lanadi. Nafaqa miqdori belgilanadi."))
    store.upsert_article(_article("t_art_2", "Transport vositasini haydash qoidalari belgilanadi."))
    hits = store.bm25_search("nogironlik pensiyasi qanday to'lanadi", language="uz", top_k=5)
    assert hits and hits[0]["canonical_id"] == "t_art_1"


# --- long units: one full-text row per chunk --------------------------------------------------------------------------

def _long_article(cid, needle=""):
    filler = "Ushbu band bo'yicha tegishli tartib belgilanadi va vakolatli organ tomonidan qo'llaniladi. " * 4
    paras = [f"{i}. {filler}" for i in range(1, 80)]
    if needle:
        paras[55] = f"56. {needle}"
    return _article(cid, "\n".join(paras), title="Uzun modda")


def test_a_paragraph_deep_in_a_long_unit_is_found(tmp_path, monkeypatch):
    needle = "Kunduzgi parvarish xizmatini ko'rsatuvchi tadbirkorlar soliqlardan ozod etiladi"
    short = _article("t_short", "Kunduzgi parvarish xizmati haqida qisqa qoida.", title="Qisqa")
    long_ = _long_article("t_long", needle)

    def search(chunk_min):
        monkeypatch.setattr(settings, "FTS_CHUNK_MIN_CHARS", chunk_min)
        store = SqliteFtsStore(str(tmp_path / f"t{chunk_min}.db"))
        store.upsert_article(short)
        store.upsert_article(long_)
        return [h["canonical_id"] for h in store.bm25_search("kunduzgi parvarish tadbirkorlar soliqlardan ozod", "uz", 5)]

    with_chunks = search(6000)
    assert with_chunks[0] == "t_long" and with_chunks.count("t_long") == 1       # found, and listed once
    assert len(set(with_chunks)) == len(with_chunks)
    assert len(long_.get_text("uz")) > 6000


def test_short_units_get_no_chunk_rows():
    from src.storage.fts_store import fts_rows
    assert len(fts_rows(_article("t_s", "Qisqa matn."))) == 1
    assert len(fts_rows(_long_article("t_l"))) > 3


def test_link_metadata_comes_from_sqlite_without_loading_the_texts(tmp_path):
    art = _article("t_meta", "Matn " * 50)
    art.metadata.source_element_ids = ["e1", "e2"]
    art.metadata.ru_document_id = "-77"
    store = SqliteFtsStore(str(tmp_path / "m.db"))
    store.upsert_article(art)
    recs = list(store.iter_link_metadata())
    assert len(recs) == 1
    r = recs[0]
    assert r["canonical_id"] == "t_meta" and r["law_id"] == "t" and r["ru_document_id"] == "-77"
    assert r["source_element_ids"] == ["e1", "e2"] and r["source_url"] == "https://lex.uz/docs/1"
    assert "translations" not in r
