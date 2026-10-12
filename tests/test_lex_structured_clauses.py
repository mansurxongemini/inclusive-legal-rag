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
