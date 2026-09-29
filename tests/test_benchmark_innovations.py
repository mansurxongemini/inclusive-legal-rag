import pytest
from src.nlp.legal_synonyms import LegalSynonymExpander
from src.nlp.query_decomposer import LegalQueryDecomposer
from src.generation.validator import CitationValidator
from src.storage.hybrid_store import HybridStore


def test_legal_synonym_expander():
    # Test colloquial term expansion
    query = "Shtat qisqarganda kim birinchi navbatda ishda qoladi?"
    expanded = LegalSynonymExpander.expand_terms(query)
    assert len(expanded) > 0
    assert any("afzallik huquqi" in term or "167-modda" in term for term in expanded)

    # Test medical and disability colloquial term expansion
    query_med = "dekret puli va bolnichniy qanday to'lanadi?"
    enriched = LegalSynonymExpander.build_enriched_search_query(query_med)
    assert "homiladorlik" in enriched or "vaqtincha" in enriched


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
    batch = store.get_articles_batch(["constitution_uz_art_1", "bojxona_code_art_1", "non_existent_cid"])
    assert isinstance(batch, dict)
    assert "constitution_uz_art_1" in batch
    assert batch["constitution_uz_art_1"].metadata.article_number in ("1-modda", "1")
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

