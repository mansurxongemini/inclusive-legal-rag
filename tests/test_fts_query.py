"""Full-text query building: stopwords are dropped, words are cut to their search stem, codes stay whole, and an
inflected question word finds the unit that holds another form of it."""
import pytest

from src.config import settings
from src.nlp.stemming import search_stem
from src.schema.canonical import CanonicalArticle
from src.storage.fts_store import SqliteFtsStore, build_fts_terms


def test_stems_strip_case_and_plural_endings_and_keep_codes():
    assert search_stem("bolaning") == "bola"
    assert search_stem("nafaqalarni") == "nafaqa"
    assert search_stem("nogironligidan") == "nogiron" and search_stem("nogironlik") == "nogiron"
    assert search_stem("pensiyalarni") == "pensiya"
    assert search_stem("VMQ-62") == "VMQ-62" and search_stem("483-modda") == "483-modda"
    assert search_stem("инвалидности") == "инвал" and search_stem("налога") == "налог"
    assert search_stem("soliq") == "soliq" and search_stem("ish") == "ish"       # short words are kept


def test_terms_drop_question_words_but_never_return_nothing():
    terms = build_fts_terms("Nogironligi bo'lgan bolaga qanday nafaqa to'lanadi?")
    assert '"qanday"*' not in terms and '"nafaqa"*' in terms and '"Nogiron"*' in terms
    assert build_fts_terms("qanday mumkin") == ['"qanday"*', '"mumkin"*']          # only stopwords: keep them


def test_stemming_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "FTS_STEM_PREFIX", 0)
    monkeypatch.setattr(settings, "FTS_STOPWORDS", False)
    assert build_fts_terms("qanday nogironligidan") == ['"qanday"*', '"nogironligidan"*']


def _article(cid, text, title="Qoida"):
    return CanonicalArticle(
        canonical_id=cid,
        metadata={"law_id": "t", "law_title": {"uz": "Sinov"}, "law_number": "Q-1", "article_number": "1-modda",
                  "article_title": {"uz": title}, "source_url": "https://lex.uz/docs/1", "effective_date": "2024-01-01",
                  "last_verified_date": "2026-10-01", "source_hash": "sha256:x", "category": "social_protection"},
        translations={"uz": text},
    )


def test_an_inflected_question_word_finds_the_unit(tmp_path):
    store = SqliteFtsStore(str(tmp_path / "t.db"))
    store.upsert_article(_article("t_art_1", "Nogironlik pensiyasi har oyda to'lanadi. Nafaqa miqdori belgilanadi."))
    store.upsert_article(_article("t_art_2", "Transport vositasini haydash qoidalari belgilanadi."))
    # the question has other forms of the unit's words: nogironligi, pensiyalar
    hits = store.bm25_search("Nogironligi bo'lgan shaxslarning pensiyalari qanday to'lanadi", language="uz", top_k=5)
    assert hits and hits[0]["canonical_id"] == "t_art_1"
