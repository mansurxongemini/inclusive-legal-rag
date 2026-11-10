from src.nlp.legal_synonyms import LegalSynonymExpander
from src.nlp.query_decomposer import LegalQueryDecomposer
from src.generation.validator import CitationValidator
from src.storage.hybrid_store import HybridStore


def test_legal_synonym_expander():
    import re

    # colloquial wording -> statutory terminology
    expanded = LegalSynonymExpander.expand_terms("TMEK ko'rigi va aravacha olish tartibi qanday?")
    assert len(expanded) > 0
    assert any("tibbiy-ijtimoiy ekspert" in t for t in expanded)
    assert any("reabilitatsiya" in t.lower() or "aravacha" in t.lower() for t in expanded)

    enriched = LegalSynonymExpander.build_enriched_search_query("nogiron bola uchun nafaqa qancha?")
    assert "nogironligi bo'lgan" in enriched

    # terminology only: article numbers change with every code edition and must never be injected
    for key, values in __import__("src.nlp.legal_synonyms", fromlist=["x"]).LEGAL_SYNONYM_DICTIONARY.items():
        assert not any(re.search(r"\d+-modda|статья \d+", v) for v in values), key

    # short stems must not fire inside unrelated words ("karta" is not "kar" = deaf)
    assert not any("eshitish" in t for t in LegalSynonymExpander.expand_terms("bank kartasi olish"))


def test_query_decomposer_compound_question():
    complex_q = (
        "Ish beruvchi korxona shtatini qisqartirayotganda kimlarni birinchi navbatda ishda qoldirishi shart? "
        "I yoki II guruh nogironligi boʻlgan xodimlar, homilador ayollar va yolgʻiz ota-onalar uchun qonunchilikda "
        "qanday alohida kafolatlar, ogohlantirish muddatlari va kompensatsiyalar belgilangan?"
    )
    subqueries = LegalQueryDecomposer.decompose(complex_q, max_subqueries=4)
    assert len(subqueries) >= 2
    # First must be primary full query
    assert subqueries[0].aspect_tag == "primary_full"
    # Ensure subqueries contain focused aspects
    all_texts = " ".join([sq.query_text for sq in subqueries])
    assert "shtat" in all_texts
    assert "nogiron" in all_texts or "homilador" in all_texts or "ogohlantirish" in all_texts


def test_batch_article_fetching():
    store = HybridStore()
    assert store.count() > 0
    # Batch fetch existing known articles
    batch = store.get_articles_batch(["law_disability_2020_art_3", "non_existent_cid"])
    assert isinstance(batch, dict)
    assert "law_disability_2020_art_3" in batch
    assert batch["law_disability_2020_art_3"].metadata.article_number in ("3-modda", "3")
    assert "non_existent_cid" not in batch


def test_validator_normative_tier_and_quote_snippet():
    store = HybridStore()
    art = store.get_article("constitution_uz_art_1")
    if art:
        tier, rank = CitationValidator._determine_normative_tier(art)
        assert tier == "Konstitutsiya"
        assert rank == 1
        snippet = CitationValidator._extract_quote_snippet(art, "uz")
        assert len(snippet) > 10

