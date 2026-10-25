"""
Uzbek and Russian units are paired by (kind, annex, number). Annexes that number several lists 1, 2, 3 ... repeat a
key; the n-th repeat must get the n-th Russian unit, not the first one (284 units of the live corpus had the Russian
text of another list's point before 2026-10-25).
"""
from src.ingestion.corpus_builder import CorpusBuilder, SourceSpec
from src.ingestion.lex_structured import LexDocument, LexUnit


def _builder() -> CorpusBuilder:
    builder = CorpusBuilder.__new__(CorpusBuilder)  # to_articles needs no network client
    builder.today = "2026-10-25"
    return builder


def _doc(units, language="uz") -> LexDocument:
    return LexDocument(doc_id="777" if language == "uz" else "778", url="https://lex.uz/docs/777", title="Test qarori",
                       number="VMQ-77", doc_type="VMQ", body="Vazirlar Mahkamasi", adopted_date="2024-01-01",
                       effective_date="2024-01-02", units=units)


def _clause(number, text, annex="1"):
    return LexUnit(kind="clause", number=number, title="", text=text, annex_number=annex, element_ids=[f"e{number}"])


UZ = [_clause("7", "7. Qoraqalpog'iston tibbiyot instituti klinikasi."),
      _clause("7", "7. Samarqand davlat tibbiyot universiteti klinikasi.")]
RU = [_clause("7", "7. Клиника Каракалпакского медицинского института."),
      _clause("7", "7. Клиника Самаркандского государственного медицинского университета.")]


def _spec():
    return SourceSpec(lex_id="777", law_id="vmq_77_2024", number="VMQ-77", category="health_care", include="all")


def test_repeated_numbers_are_paired_in_order():
    arts, _ = _builder().to_articles(_doc(UZ), _spec(), _doc(RU, "ru"))
    by_text = {a.translations["uz"]: a.translations.get("ru") for a in arts}
    assert "Каракалпак" in by_text["7. Qoraqalpog'iston tibbiyot instituti klinikasi."]
    assert "Самарканд" in by_text["7. Samarqand davlat tibbiyot universiteti klinikasi."]


def test_repeats_get_no_russian_text_when_the_editions_disagree_on_their_count():
    arts, _ = _builder().to_articles(_doc(UZ), _spec(), _doc(RU[:1], "ru"))
    assert all("ru" not in a.translations for a in arts)


def test_a_unique_key_is_paired_as_before():
    uz = [_clause("1", "1. Umumiy qoida.")]
    ru = [_clause("1", "1. Общее положение.")]
    arts, _ = _builder().to_articles(_doc(uz), _spec(), _doc(ru, "ru"))
    assert arts[0].translations["ru"] == "1. Общее положение."


def test_russian_points_after_a_repealed_point_reach_their_own_units():
    # the Uzbek edition splits 46 off point 44 (repeal note for 45); the Russian edition, without notes, keeps it glued
    uz = [_clause("44", "44. To'rt daraja."), _clause("46", "46. I guruh mezoni.")]
    ru = [_clause("44", "44. Четыре степени.\n46. Критерий I группы.")]
    arts, _ = _builder().to_articles(_doc(uz), _spec(), _doc(ru, "ru"))
    by_text = {a.translations["uz"]: a.translations.get("ru") for a in arts}
    assert by_text["44. To'rt daraja."] == "44. Четыре степени."
    assert by_text["46. I guruh mezoni."] == "46. Критерий I группы."
