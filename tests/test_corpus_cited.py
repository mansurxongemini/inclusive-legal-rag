"""`build_disability_corpus.py cited`: acts cited by Huquq+ articles -> Latin edition, amended act, in-force check."""
import importlib.util
from pathlib import Path

from src.ingestion.lex_structured import LexDocumentParser
from src.nlp.transliteration import normalize_apostrophes

_spec = importlib.util.spec_from_file_location(
    "build_disability_corpus", Path(__file__).resolve().parents[1] / "scripts" / "build_disability_corpus.py")
corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(corpus)


def _page(title: str, banner: str = "", body: str = "") -> str:
    return (f"<html><head><title>{title}</title></head><body>"
            + (f'<div class="act_warning">{banner}</div>' if banner else "")
            + f'<div id="divCont">{body}</div></body></html>')


class FakeLex:
    def __init__(self, pages):
        self.pages = pages

    def fetch_document(self, doc_id, force=False):
        return self.pages.get(doc_id)

    def fetch_url(self, url, force=False):
        return self.pages.get(corpus._lex_id_of(url))


def test_amending_titles_are_recognised():
    amending = [
        "“Jismoniy va yuridik shaxslarning murojaatlari toʻgʻrisida”gi Qonuniga oʻzgartish va qoʻshimchalar kiritish haqida",
        "Hukumatning ayrim qarorlariga oʻzgartirishlar kiritish toʻgʻrisida",
        "Nizomga qoʻshimcha kiritish haqida",
    ]
    plain = ["Davlat boji toʻgʻrisida", "Aholi bandligi toʻgʻrisida"]
    assert all(corpus._AMENDING_TITLE.search(normalize_apostrophes(t)) for t in amending)
    assert not any(corpus._AMENDING_TITLE.search(normalize_apostrophes(t)) for t in plain)


def test_amended_act_is_the_linked_act_whose_title_is_repeated():
    base = "Bolalarni davlat maktabgacha taʼlim tashkilotlariga qabul qilish boʻyicha maʼmuriy reglament"
    amending_title = ("Vazirlar Mahkamasining “Bolalarni davlat maktabgacha taʼlim muassasalariga qabul qilish "
                      "boʻyicha maʼmuriy reglament” toʻgʻrisidagi qaroriga oʻzgartish kiritish haqida")
    html = _page(amending_title, body='<a href="/uz/docs/-900">x</a><a href="/uz/docs/-900">x</a>'
                                       '<a href="/uz/docs/-901">y</a>')
    lex = FakeLex({"-900": _page(base), "-901": _page("Davlat xizmatlari koʻrsatish toʻgʻrisida")})
    assert corpus._amended_act(lex, LexDocumentParser(), html, amending_title) == ("-900", "")


def test_amended_act_that_lost_force_is_not_added():
    title = "“Jismoniy va yuridik shaxslarning murojaatlari toʻgʻrisida”gi Qonunga oʻzgartish kiritish haqida"
    html = _page(title, body='<a href="/uz/docs/-2509996">q</a>')
    lex = FakeLex({"-2509996": _page("Jismoniy va yuridik shaxslarning murojaatlari toʻgʻrisida",
                                     banner="Hujjat yangi tahrirda qabul qilingan")})
    target, why = corpus._amended_act(lex, LexDocumentParser(), html, title)
    assert target == "" and why.startswith("base_act_not_in_force")


def test_act_amending_several_acts_has_no_single_base():
    title = "Oʻzbekiston Respublikasining ayrim qonun hujjatlariga oʻzgartish kiritish toʻgʻrisida"
    assert corpus._amended_act(FakeLex({}), LexDocumentParser(), _page(title), title) == ("", "amends_several_acts")


def test_cited_ids_fold_onto_the_latin_edition():
    ru_page = ('<html><head><title>Ob utverjdenii</title></head><body>'
               '<div title="O\'zbekcha" onclick="openUrl(\'/uz/docs/-6236060\')">O’zb</div></body></html>')
    lex = FakeLex({"-6236060": _page("Nizom"), "6236070": ru_page})
    parser = LexDocumentParser()
    assert corpus._latin_edition(lex, parser, "-6236060") == "-6236060"
    assert corpus._latin_edition(lex, parser, "6236060") == "-6236060"     # Cyrillic edition id
    assert corpus._latin_edition(lex, parser, "6236070") == "-6236060"     # Russian edition id
    assert corpus._latin_edition(lex, parser, "123") == ""
