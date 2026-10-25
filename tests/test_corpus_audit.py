"""Corpus quality gate (scripts/audit_corpus.py): hard problems fail the build, glued headings and swallowed points are reported."""
from src.ingestion.corpus_audit import audit, glued_heading, hard_problems, swallowed_points

LEX = "https://lex.uz/uz/docs/-5049511#-5049549"


def test_hard_problems_are_found():
    assert hard_problems("a", "Matn.", LEX, "lex") == []
    assert hard_problems("a", "", LEX, "lex") == ["no_uzbek_text"]
    # three units of the live store carried U+FFFD from the Lex.uz page ("yechiml�rni") until 2026-10-25
    assert hard_problems("a", "yechiml�rni", LEX, "lex") == ["broken_character"]
    assert hard_problems("a", "Matn<br>davomi", LEX, "lex") == ["html_in_text"]
    assert hard_problems("a", "Matn.", "https://evil.example/docs/1", "lex") == ["not_a_lex_link"]
    assert hard_problems("hp_uz_1_1", "Maqola.", "https://huquqplus.uz/p/1", "huquqplus") == []


def test_a_heading_glued_to_the_end_of_a_point_is_reported():
    assert glued_heading("5. IPTK vazifalarini ham amalga oshiradi.\n3-bob. IPTK faoliyatini tashkil etish") == \
        "3-bob. IPTK faoliyatini tashkil etish"
    assert glued_heading("7. Qaror ijrosini ta'minlasin.\nIII. Tashkiliy chora-tadbirlar") == "III. Tashkiliy chora-tadbirlar"
    assert glued_heading("1. Oddiy band.\nIkkinchi xatboshi davom etadi va nuqta bilan tugaydi.") == ""


def test_points_swallowed_by_an_earlier_point_are_reported():
    text = "44. To'rt daraja. 46. Birinchi guruh mezoni. 47. Ikkinchi guruh mezoni."
    assert swallowed_points("vmq_62_2022_a9_p_44", text, {"vmq_62_2022_a9_p_44"}) == [46, 47]
    assert swallowed_points("vmq_62_2022_a9_p_44", text, {"vmq_62_2022_a9_p_46", "vmq_62_2022_a9_p_47"}) == []


def test_audit_summarizes():
    report = audit([("u1", "Matn.", LEX, "lex"), ("u2", "bu�", LEX, "lex")])
    assert report["units"] == 2 and report["hard"] == {"broken_character": {"count": 1, "examples": ["u2"]}}


def test_a_russian_text_holding_later_points_is_reported():
    units = [("x_p_44", "44. To'rt daraja.", LEX, "lex", "44. Четыре степени.\n46. Критерий I группы."),
             ("x_p_46", "46. I guruh mezoni.", LEX, "lex", "")]
    assert audit(units)["russian_overflow"] == {"count": 2, "examples": ["x_p_44", "x_p_46"]}
