"""Offline tests for havola_new.py (no network): term matching, Lex.uz export parsing, unit/article analysis."""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("havola_new", Path(__file__).resolve().parents[1] / "havola_new.py")
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)


@pytest.mark.parametrize("text,til,expected", [
    ("nogironligi boʻlgan shaxslar", "uz", True),
    ("НОГИРОНЛИГИ БЎЛГАН шахслар", "uz", True),
    ("Brayl alifbosi asosida", "uz", True),
    ("kar, soqov, koʻr va h.k.", "uz", True),
    ("Oʻzbekiston karlar jamiyati", "uz", True),
    ("alohida taʼlim ehtiyojlari boʻlgan bolalar", "uz", True),
    ("jismoniy-aqliy rivojlanishida nuqsonlar bilan", "uz", True),
    ("qisman kasbiy mehnat qobiliyatini yoʻqotishga", "uz", True),
    ("лиц с ограниченными возможностями", "ru", True),
    ("отправления для слепых", "ru", True),
    # look-alikes that are not about disability
    ("koʻr ichakning xavfli oʻsmasi", "uz", False),
    ("elektr-kar va avto-karlarning", "uz", False),
    ("professori Sanjib Kar; 2.", "uz", False),
    ("koʻrish imkoniyati cheklangan sharoitlarda", "uz", False),
    ("bolalarning alohida ehtiyojlarini", "uz", False),
    ("iqtisodiyot rivojlanishidan orqada qolmoqda", "uz", False),
    ("mehnat qobiliyatini vaqtincha yoʻqotganlik boʻyicha nafaqa", "uz", False),
    ("toʻsiqsiz harakatlanish (free-flow)", "uz", False),
    ("artist-mimika va imo-ishora teatrlarida", "uz", False),
    ("глухие заклепки", "ru", False),
    ("слепые стволы", "ru", False),
    ("стифлос тн", "ru", False),
    ("пособие по временной утрате трудоспособности", "ru", False),
    ("ограниченные возможности развивающихся стран", "ru", False),
])
def test_find_terms(text, til, expected):
    assert bool(h.find_terms(text, til)) is expected


def test_parse_export_reads_every_row():
    doc = ("<html><body><table border=1><thead><tr><th>T/r</th></tr></thead><tbody>"
           "<tr><td>1</td><td>PF-177,<br />28.08.2026-y.</td><td>Birinchi hujjat</td><td>08.09.2026-y.</td>"
           "<td><a href=\"http://lex.uz/uz/docs/-8458324\">http://lex.uz/uz/docs/-8458324</a></td></tr>"
           "<tr><td>2</td><td>13.12.2006-y.</td><td>Nogironlar huquqlari toʻgʻrisida</td><td>28.07.2021-y.</td>"
           "<td><a href=\"http://lex.uz/uz/docs/-5501227\">http://lex.uz/uz/docs/-5501227</a></td>"
           "</tbody></table></body></html>")
    rows = h.LexSearch.parse_export(doc)
    assert [r["id"] for r in rows] == ["-8458324", "-5501227"]
    assert rows[0]["number"] == "PF-177" and rows[0]["date"] == "2026-08-28" and rows[0]["effective"] == "2026-09-08"
    assert rows[1]["number"] == "" and rows[1]["title"] == "Nogironlar huquqlari toʻgʻrisida"


def _el(role, eid, text):
    return (f'<div class="{role} lx_elem" onmousemove="lx_mo(event,{eid})"><div class="lx_elem2"><div class="lx_elem3">'
            f'<span>Hujjatga taklif yuborish</span></div></div><div name="{eid}" id="{eid}">{text}</div></div>')


def test_analyse_keeps_live_articles_and_drops_repealed_and_repeal_lists():
    page = (
        '<div class="docHeader__item-label">Oʻzbekiston Respublikasining Qonuni, 15.10.2020 yildagi OʻRQ-641-son</div>'
        + _el("ACT_TITLE", -1, "Ijtimoiy himoya toʻgʻrisida")
        + _el("CLAUSE_DEFAULT", -2, "5-modda. Imtiyozlar")
        + '<div class="INDEXES_ON_REF lx_no_select" style="display:none"><div id="x">[OKOZ: 06.10.00.00 Nogironligi '
          'boʻlgan shaxslar]</div></div>'
        + _el("ACT_TEXT", -3, "Nogironligi boʻlgan shaxslarga imtiyoz beriladi.")
        + _el("CLAUSE_DEFAULT", -4, "6-modda. Kuchini yoʻqotgan")
        + _el("ACT_TEXT", -5, "Nogironlik pensiyasi haqidagi eski norma.")
        + _el("CLAUSE_DEFAULT", -6, "7-modda. Ayrim hujjatlarni oʻz kuchini yoʻqotgan deb topish")
        + _el("ACT_TEXT", -7, "“Nogironlarni ijtimoiy himoya qilish toʻgʻrisida”gi Qonun.")
        + _el("CHANGES_ORIGINS", -8, "(8-modda “Nogironligi boʻlgan shaxslar toʻgʻrisida”gi Qonun tahririda)")
        + _el("CLAUSE_DEFAULT", -9, "8-modda. Yakuniy qoidalar")
    )
    info = h.parse_document(page)
    assert info["kind"].startswith("Oʻzbekiston Respublikasining Qonuni")
    res = h.analyse(info, "uz")
    units = {u["label"]: u for u in res["units"]}
    assert not res["title_hit"]
    assert units["5-modda"]["id"] == "-3" and not units["5-modda"]["weak"]     # live article, OKOZ note ignored
    assert "6-modda" not in units                                              # repealed article
    assert units["7-modda"]["weak"]                                            # only a repeal list
    assert "8-modda" not in units                                              # amendment note ignored


def test_repealed_banner_and_level():
    page = '<div class="act_warning"> Hujjat kuchini yoʻqotgan&nbsp;01.07.2025 </div>' + _el("ACT_TEXT", -1, "Matn")
    assert h.parse_document(page)["repealed"]
    assert h.classify_level({"nat"}, "Oʻzbekiston Respublikasining Mehnat kodeksi", "") == "kodeks"
    assert h.classify_level({"nat"}, "Oʻzbekiston Respublikasi Vazirlar Mahkamasining qarori, 08.02.2022", "") == "vmq"
    assert h.classify_level({"int"}, "Xalqaro hujjat", "") == "xalqaro"
    assert h.flip_id("-5049511") == "5049511" and h.flip_id("8421001") == "-8421001"
