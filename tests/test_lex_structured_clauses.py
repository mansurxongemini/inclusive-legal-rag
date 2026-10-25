"""Clause numbering of Lex.uz resolutions (no "N-modda" headings): amendments insert clauses such as "2-1."."""
from src.ingestion.lex_structured import LexDocumentParser


def _elem(eid: int, text: str) -> str:
    # the element markup Lex.uz serves (trimmed: the toolbar spans are irrelevant to parsing)
    return (f'<div class="ACT_TEXT lx_elem" onmousemove="lx_mo(event,{eid})"><div class="lx_elem2"></div>'
            f'<div name="{eid}" id="{eid}">{text}</div></div>')


def test_inserted_clause_is_its_own_unit_and_numbering_continues():
    html = "<html><body>" + "".join([
        _elem(101, "1. Birinchi band matni."),
        _elem(102, "2. Ikkinchi band matni."),
        _elem(910, "2-1. Keyinroq kiritilgan band matni."),
        _elem(103, "3. Uchinchi band matni."),
    ]) + "</body></html>"
    doc = LexDocumentParser().parse(html, "-1", language="uz")
    clauses = [(u.number, u.element_ids) for u in doc.units if u.kind == "clause"]
    assert clauses == [("1", ["101"]), ("2", ["102"]), ("2-1", ["910"]), ("3", ["103"])]


def _page(banner: str) -> str:
    # the banner Lex.uz shows above the text of an act that is no longer the operative edition
    return ('<html><body><div class="act_warning">' + banner + '</div>'
            + _elem(101, "1. Birinchi band matni.") + "</body></html>")


def test_act_warning_banner_marks_the_act_repealed():
    doc = LexDocumentParser().parse(_page("Hujjat kuchini yo‘qotgan&nbsp;20.01.2026"), "-1", language="uz")
    assert (doc.status, doc.repealed_date) == ("repealed", "2026-01-20")
    ru = LexDocumentParser().parse(_page("Акт утратил силу&nbsp;08.02.2022"), "1", language="ru")
    assert (ru.status, ru.repealed_date) == ("repealed", "2022-02-08")


def test_act_readopted_in_new_edition_is_not_in_force():
    doc = LexDocumentParser().parse(_page("Hujjat yangi tahrirda qabul qilingan"), "-1", language="uz")
    assert doc.status == "repealed"


def test_no_banner_keeps_the_act_active():
    doc = LexDocumentParser().parse(_page(" "), "-1", language="uz")
    assert doc.status == "active"


def _note(eid: int, text: str) -> str:
    return (f'<div class="CHANGES_ORIGINS lx_no_select"><label></label><div name="{eid}" id="{eid}">{text}</div></div>')


def test_a_point_after_a_repealed_one_starts_its_own_unit():
    # VMQ-62 annex 9 as Lex.uz serves it: point 45 repealed by VMQ-587 (only its note is left), 46-47 follow
    html = "<html><body>" + "".join([
        _elem(144, "44. Organizm funksiyalari buzilishlari to'rtta darajaga ajratiladi:"),
        _elem(145, "I daraja — yengil buzilishlar;"),
        _note(900, "(45-band Vazirlar Mahkamasining 2025-yil 16-sentabrdagi 587-sonli qaroriga asosan o'z kuchini yo'qotgan)"),
        _elem(146, "46. Birinchi guruhni belgilash mezoni."),
        _elem(147, "47. Ikkinchi guruhni belgilash mezoni."),
        _elem(150, "50. Bu raqam bo'shliqdan keyin keladi, lekin 48-49 bekor qilinmagan."),
    ]) + "</body></html>"
    doc = LexDocumentParser().parse(html, "-1", language="uz")
    clauses = [(u.number, u.element_ids) for u in doc.units if u.kind == "clause"]
    # 46 and 47 are units; 50 stays inside 47: 48 and 49 were not repealed, so the jump is not trusted
    assert clauses == [("44", ["144", "145"]), ("46", ["146"]), ("47", ["147", "150"])]
