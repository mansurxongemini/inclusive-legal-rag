"""
Structure-aware parser for Lex.uz legal documents.

Lex.uz renders every paragraph as ``<div class="<ROLE> lx_elem"> ... <div name="-ID" id="-ID">text</div></div>``
where ROLE says what the paragraph is (document title, chapter heading, article header, body text, amendment
note, classifier annotation, ...). This module uses those roles instead of guessing from text, and produces
normalized units (articles of a law, clauses of a resolution, annex clauses) with their hierarchy.

What is deliberately NOT part of a unit's text:
  * classifier annotations ``[ OKOZ: ... ]`` / ``[ TSZ: ... ]`` that Lex.uz injects into paragraphs,
  * site UI ("Hujjatga taklif yuborish", "Audioni tinglash", ...),
  * amendment notes (kept separately as `LexAmendmentNote`) and LexUZ commentary.
"""
import html as html_lib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, NavigableString, Tag

from src.nlp.transliteration import cyrillic_to_latin, detect_script, normalize_apostrophes

logger = logging.getLogger(__name__)

# --- element roles -------------------------------------------------------------------------------------------
ROLE_TITLE = "ACT_TITLE"
ROLE_CHAPTER = "TEXT_HEADER_DEFAULT"
ROLE_ARTICLE = "CLAUSE_DEFAULT"
ROLE_ANNEX_BANNER = {"APPL_BANNER_LANDSCAPE_TITLE", "APPL_BANNER_PORTRAIT_TITLE", "APPL_BANNER_TITLE"}
ROLE_ANNEX_TITLE = {"ACT_TITLE_APPL", "ACT_TITLE_APPL_ADD"}
ROLE_AMENDMENT = "CHANGES_ORIGINS"
ROLES_SKIPPED = {
    "COMMENT", "COMMENTLEXUZ", "INDEXES_ON_REF", "ACCEPTING_BODY", "ACT_FORM", "GRIF_PARLAMENT", "GRIF_PRESIDENT",
    "SIGNATURE", "SIGNATURE_WITH_BOLD", "ACT_ESSENTIAL_ELEMENTS", "ACT_ESSENTIAL_ELEMENTS_NUM", "BY_DEFAULT",
    "LX_PLACE_DATE", "FOOTNOTE", "TEXT_CENTER_SMALL",
}

_ANNOTATION = re.compile(r"\[\s*(?:OKOZ|TSZ|QTUK|ОКОЗ|ТСЗ)\s*:[^\]]*\]", re.IGNORECASE)
_UI_NOISE = re.compile(
    r"(Hujjatga taklif yuborish|Audioni tinglash|Hujjat elementidan havola olish|Oldingi tahrirga qarang\.?|"
    r"LexUZ sharhi)",
    re.IGNORECASE,
)
_SUP_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_SUP_FROM_UNICODE = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")

_NUM = r"(\d+(?:[\^-]\d+)?)"
_ARTICLE_RE = re.compile(
    rf"^{_NUM}\s*[-–—]?\s*(?:modda|модда|статья|moddasi)\s*[\.\:]?\s*(.*)$", re.IGNORECASE | re.DOTALL
)
_ARTICLE_RU_RE = re.compile(rf"^(?:статья|ст\.)\s*{_NUM}\s*[\.\:]?\s*(.*)$", re.IGNORECASE | re.DOTALL)
_CLAUSE_RE = re.compile(rf"^{_NUM}\.\s+(\S.*)$", re.DOTALL)
_ANNEX_NUM_RE = re.compile(
    r"(\d+)\s*[-–—]?\s*(?:son\s+)?(?:ilova|илова)|(?:приложение|прил\.)\s*(?:№|N|no\.?)?\s*(\d+)", re.IGNORECASE
)
_REPEALED_RE = re.compile(r"kuchini\s+yo[ʻ'`’‘ʼ]?qot|кучини\s+йўқот|утратил[аи]?\s+силу", re.IGNORECASE)
_DATE_DMY = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")

_UZ_MONTHS = {
    "yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6, "iyul": 7, "avgust": 8,
    "sentabr": 9, "sentyabr": 9, "oktabr": 10, "oktyabr": 10, "noyabr": 11, "dekabr": 12,
}


# --- data model ----------------------------------------------------------------------------------------------
@dataclass
class LexAmendmentNote:
    raw: str
    date: Optional[str] = None            # ISO
    amending_act: Optional[str] = None    # e.g. "O'RQ-683"
    action: str = ""                      # tahririda | o'zgartirilgan | to'ldirilgan | chiqarib tashlangan | ...


@dataclass
class LexUnit:
    kind: str                              # article | clause | annex_clause | preamble
    number: str                            # "15", "30-1" (superscript article), "" for preamble
    title: str = ""
    text: str = ""
    chapter: str = ""
    section: str = ""
    annex_number: Optional[str] = None
    annex_title: str = ""
    element_ids: List[str] = field(default_factory=list)
    amendments: List[LexAmendmentNote] = field(default_factory=list)
    status: str = "active"                 # active | repealed
    tables: int = 0

    @property
    def display_number(self) -> str:
        suffix = "modda" if self.kind == "article" else "band"
        if self.kind == "preamble":
            return "preambula"
        prefix = f"{self.annex_number}-ilova, " if self.annex_number else ""
        return f"{prefix}{self.number}-{suffix}"


@dataclass
class LexDocument:
    doc_id: str
    url: str
    title: str = ""
    number: str = ""                       # normalized: O'RQ-641 / PF-115 / VMQ-440 / PQ-266
    raw_number: str = ""
    doc_type: str = "Boshqa"               # Qonun | Kodeks | Farmon | PQ | VMQ | Buyruq | Konvensiya | ...
    body: str = ""                         # adopting body
    adopted_date: Optional[str] = None
    effective_date: Optional[str] = None
    status: str = "active"                 # active | repealed
    repealed_date: Optional[str] = None
    script: str = "latin"                  # script of the source text
    language_links: Dict[str, str] = field(default_factory=dict)
    okoz: List[str] = field(default_factory=list)
    units: List[LexUnit] = field(default_factory=list)
    toc_titles: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# --- helpers -------------------------------------------------------------------------------------------------
def _dmy_to_iso(d: str, m: str, y: str) -> Optional[str]:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def parse_dmy(text: str) -> Optional[str]:
    m = _DATE_DMY.search(text or "")
    return _dmy_to_iso(*m.groups()) if m else None


def _norm(text: str) -> str:
    text = html_lib.unescape(text or "").replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _clean_inline(text: str) -> str:
    text = _ANNOTATION.sub(" ", text)
    text = _UI_NOISE.sub(" ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _unify_apostrophes(text: str) -> str:
    """Lex.uz mixes ʻ ʼ ’ ‘ ` — queries are normalized to ASCII ', so the corpus must be too."""
    return normalize_apostrophes(text)


def normalize_law_number(raw: str, body: str = "") -> str:
    """Brings Latin/Cyrillic/Russian spellings of an act number to one canonical form."""
    s = normalize_apostrophes(_norm(raw)).strip(" .")
    s = re.sub(r"[-\s]*(?:сон|son)\s*$", "", s, flags=re.IGNORECASE).lstrip("№ ").strip(" -")
    # Cyrillic prefixes (ЎРҚ, ПҚ, ВМҚ, ЗРУ ...) -> Latin before matching
    upper = (cyrillic_to_latin(s) if detect_script(s) == "cyrillic" else s).upper()
    upper = upper.replace("О'RQ", "O'RQ")
    table = [
        (r"^(?:O'?RQ|ORQ|ZRU|ZRU)[-\s]*(.+)$", "O'RQ-"),
        (r"^(?:PF|UP)[-\s]*(.+)$", "PF-"),
        (r"^(?:PQ|PP|PK)[-\s]*(.+)$", "PQ-"),
        (r"^(?:VMQ|VMK|PKM)[-\s]*(.+)$", "VMQ-"),
    ]
    for pattern, prefix in table:
        m = re.match(pattern, upper)
        if m:
            return prefix + m.group(1).strip()
    body_l = normalize_apostrophes(body).lower()
    if re.fullmatch(r"\d+(?:-[IVX]+)?", upper):
        if any(k in body_l for k in ("vazirlar mahkamasi", "вазирлар маҳкамаси", "кабинет министров")):
            return f"VMQ-{upper}"
    return upper or s


def detect_doc_type(title: str, body: str, header_line: str = "") -> str:
    hay = normalize_apostrophes(f"{header_line} {body} {title}").lower()
    pairs = [
        ("konvensiya", "Konvensiya"), ("конвенци", "Konvensiya"),
        ("kodeks", "Kodeks"), ("кодекс", "Kodeks"),
        ("prezidentining farmon", "Farmon"), ("farmon", "Farmon"), ("фармон", "Farmon"),
        ("prezidentining qaror", "PQ"), ("президентнинг қарор", "PQ"),
        ("vazirlar mahkamasining qaror", "VMQ"), ("вазирлар маҳкамасининг қарор", "VMQ"),
        ("buyrug", "Buyruq"), ("буйруқ", "Buyruq"),
        ("qonun", "Qonun"), ("қонун", "Qonun"),
        ("qaror", "Qaror"), ("қарор", "Qaror"),
    ]
    for needle, label in pairs:
        if needle in hay:
            return label
    return "Boshqa"


def _to_latin(text: str, script: str) -> str:
    return cyrillic_to_latin(text) if script == "cyrillic" else text


def _match_article(line: str):
    """(number, rest) when the line opens an article in Uzbek ('15-modda. ...') or Russian ('Статья 15. ...')."""
    m = _ARTICLE_RE.match(line) or _ARTICLE_RU_RE.match(line)
    return (m.group(1), m.group(2)) if m else None


def _article_number(raw: str) -> str:
    """'30^1' -> '30-1'."""
    return raw.replace("^", "-")


# --- element extraction --------------------------------------------------------------------------------------
@dataclass
class _Element:
    role: str
    element_id: str
    text: str
    tables: int = 0


def _render(inner: Tag) -> Tuple[str, int]:
    """Plain text of one paragraph; <sup> becomes ^n (article numbers) and tables become markdown rows."""
    tables = inner.find_all("table")
    table_texts: List[str] = []
    for tbl in tables:
        rows = []
        for tr in tbl.find_all("tr"):
            cells = [_norm(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append("| " + " | ".join(cells) + " |")
        table_texts.append("\n".join(rows))
        tbl.replace_with(NavigableString(f"\n@@TABLE{len(table_texts) - 1}@@\n"))

    for sup in inner.find_all("sup"):
        sup.replace_with(NavigableString("^" + sup.get_text(strip=True)))
    for br in inner.find_all("br"):
        br.replace_with(NavigableString("\n"))

    text = inner.get_text("", strip=False)
    for i, tt in enumerate(table_texts):
        text = text.replace(f"@@TABLE{i}@@", tt)
    lines = [_norm(line) for line in text.split("\n")]
    return "\n".join(line for line in lines if line), len(table_texts)


def _fix_superscripts(text: str) -> str:
    """Keep ^n only where it denotes an article/clause index (30^1-modda); elsewhere use a real superscript."""
    keep = re.sub(
        r"(\d)\^(\d+)(?=\s*[-–—]?\s*(?:modda|band|qism|bob|bo[ʻ'`’‘ʼ]?lim|ilova|модда|банд|бўлим|боб|статья|пункт))",
        r"\1-\2",
        text,
        flags=re.IGNORECASE,
    )
    keep = re.sub(r"(?i)\b(статья|ст\.)\s*(\d+)\^(\d+)", r"\1 \2-\3", keep)
    return re.sub(r"\^(\d+)", lambda m: m.group(1).translate(_SUP_DIGITS), keep)


def extract_elements(soup: BeautifulSoup) -> List[_Element]:
    out: List[_Element] = []
    for div in soup.select("div.lx_elem"):
        classes = [c for c in (div.get("class") or []) if c not in ("lx_elem", "lx_no_select")]
        if not classes:
            continue
        inner = None
        for child in div.find_all("div", recursive=False):
            if child.has_attr("name") and child.has_attr("id"):
                inner = child
                break
        if inner is None:
            continue
        text, n_tables = _render(inner)
        out.append(_Element(role=classes[0], element_id=str(inner.get("id")), text=text, tables=n_tables))
    return out


# --- document-level metadata ---------------------------------------------------------------------------------
def _parse_header(soup: BeautifulSoup, doc: LexDocument) -> None:
    title_tag = soup.find("title")
    raw_title = _norm(title_tag.get_text()) if title_tag else ""
    doc.title = raw_title

    header_el = soup.select_one("div.docHeader")
    labels: List[str] = []
    header_text = ""
    if header_el is not None:
        for node in header_el.select(".docHeader__item-label, .docHeader__item-value"):
            t = _norm(node.get_text(" ", strip=True))
            if t:
                labels.append(t)
        header_text = " | ".join(labels)

    if labels:
        first = labels[0]
        # "Oʻzbekiston Respublikasining Qonuni, 15.10.2020 yildagi O‘RQ-641-son"
        m = re.match(r"^(?P<body>.+?),\s*(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})\s*(?P<rest>.*)$", first)
        if m:
            doc.body = _norm(m.group("body"))
            doc.adopted_date = _dmy_to_iso(m.group("d"), m.group("m"), m.group("y"))
            reg = re.search(r"ro[ʻ'`’‘ʼ]?yxat\s+raqami\s*([\w\-/]+)|рўйхат\s+рақами\s*([\w\-/]+)",
                            normalize_apostrophes(m.group("rest")), re.IGNORECASE)
            rest = re.sub(r"\b(?:yildagi|йилдаги|йил|г\.?|года)\b", " ", m.group("rest"), flags=re.IGNORECASE)
            rest = re.sub(r"№", " ", rest)
            rest = re.sub(r"[-\s]*(?:son|сон)\s*$", "", rest.strip(), flags=re.IGNORECASE).strip(" -")
            # Ministry orders are identified by their Ministry-of-Justice registration number
            doc.raw_number = f"REG-{reg.group(1) or reg.group(2)}" if reg else rest.strip()

    for i, lab in enumerate(labels):
        low = lab.lower()
        if re.search(r"kuchga kirish sanasi|кучга кириш санаси|дата вступления в силу", low) and i + 1 < len(labels):
            doc.effective_date = parse_dmy(labels[i + 1]) or doc.effective_date
    rm = re.search(
        r"(?:hujjat\s+)?kuchini\s+yo[ʻ'`’‘ʼ]qotgan|кучини\s+йўқотган|утратил[аи]?\s+силу",
        header_text, re.IGNORECASE,
    )
    if rm:
        doc.status = "repealed"
        doc.repealed_date = parse_dmy(header_text[rm.end():rm.end() + 40])

    # <title>: "O‘RQ-641-сон 15.10.2020. Nogironligi ..."  or  "440-сон 13.08.2026. 1941-1945..."
    tm = re.match(r"^\s*(?P<num>[^\s]+?)\s*[-–—]?\s*(?:сон|son)\s+(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})\.?\s*(?P<t>.*)$",
                  raw_title)
    if tm:
        doc.raw_number = doc.raw_number or tm.group("num")
        doc.adopted_date = doc.adopted_date or _dmy_to_iso(tm.group("d"), tm.group("m"), tm.group("y"))
        doc.title = _norm(tm.group("t"))
    else:
        tm2 = re.match(r"^\s*(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})\.?\s*(?P<t>.*)$", raw_title)
        if tm2:
            doc.adopted_date = doc.adopted_date or _dmy_to_iso(tm2.group("d"), tm2.group("m"), tm2.group("y"))
            doc.title = _norm(tm2.group("t"))

    doc.number = normalize_law_number(doc.raw_number, doc.body) if doc.raw_number else ""
    doc.doc_type = detect_doc_type(doc.title, doc.body, header_text)
    if not doc.effective_date:
        doc.effective_date = doc.adopted_date

    # official language alternatives: <div title="На русском" onclick="openUrl('/docs/123')">
    for node in soup.find_all(attrs={"title": True, "onclick": True}):
        mm = re.search(r"openUrl\(['\"]((?:/[a-z]{2})?/docs/[^'\"]+)['\"]\)", node.get("onclick", ""))
        if not mm:
            continue
        label = node.get("title", "").strip().lower()
        url = f"https://lex.uz{mm.group(1)}"
        if "русск" in label:
            doc.language_links["ru"] = url
        elif "english" in label or "англ" in label:
            doc.language_links["en"] = url
        elif "ўзбекча" in label:
            doc.language_links["uz_cyrl"] = url
        elif "o'zbekcha" in label or "oʻzbekcha" in label or "ozbekcha" in label:
            doc.language_links["uz_latn"] = url


# --- main parser ---------------------------------------------------------------------------------------------
class LexDocumentParser:
    """Turns the HTML of one Lex.uz document into `LexDocument` with ordered, hierarchical units."""

    def parse(self, html_text: str, doc_id: str = "", url: str = "", language: str = "uz") -> LexDocument:
        soup = BeautifulSoup(html_text, "html.parser")
        doc = LexDocument(doc_id=str(doc_id), url=url or (f"https://lex.uz/uz/docs/{doc_id}" if doc_id else ""))
        _parse_header(soup, doc)

        # table of contents from the side navigation (independent cross-check for QA)
        for a in soup.select(".docNabvar__child-link a.search-text, .docNabvar__child-link p a"):
            t = _norm(a.get_text(" ", strip=True))
            if t:
                doc.toc_titles.append(t)

        # classifier categories of the document
        okoz = set()
        for node in soup.select("div.INDEXES_ON_REF"):
            for part in re.split(r"\s*/\s*|;\s*\d+\.\s*", _norm(node.get_text(" ", strip=True))):
                p = re.sub(r"^\[?\s*OKOZ:\s*(?:\d+\.\s*)?", "", part).strip(" []")
                if re.match(r"^\d{2}\.\d{2}\.\d{2}\.\d{2}\s", p):
                    okoz.add(p)
        doc.okoz = sorted(okoz)[:80]

        # amendment notes are lx_no_select blocks that follow the element they refer to
        amend_after: Dict[str, List[str]] = {}
        for node in soup.select("div.CHANGES_ORIGINS"):
            prev = node.find_previous("div", class_="lx_elem")
            note = _norm(node.get_text(" ", strip=True))
            if note:
                key = ""
                if prev is not None:
                    inner = next((c for c in prev.find_all("div", recursive=False) if c.has_attr("name")), None)
                    key = str(inner.get("id")) if inner is not None else ""
                amend_after.setdefault(key, []).append(note)

        elements = extract_elements(soup)
        for el in elements:
            el.text = _unify_apostrophes(_fix_superscripts(_clean_inline(el.text)))

        script_probe = " ".join(e.text for e in elements[:80])
        doc.script = "cyrillic" if detect_script(script_probe) == "cyrillic" else "latin"
        if not doc.title:
            ti = next((e.text for e in elements if e.role == ROLE_TITLE), "")
            doc.title = ti
        elif detect_script(doc.title) == "cyrillic" and doc.script == "latin":
            ti = next((e.text for e in elements if e.role == ROLE_TITLE), "")
            doc.title = ti or doc.title

        doc.units = self._build_units(elements, amend_after, doc)
        # Uzbek Cyrillic is converted to Latin (the platform's retrieval script); Russian is kept as is.
        if doc.script == "cyrillic" and language == "uz":
            self._transliterate(doc)
        self._qa(doc)
        return doc

    # ------------------------------------------------------------------------------------------------------
    def _build_units(self, elements: List[_Element], amend_after: Dict[str, List[str]], doc: LexDocument) -> List[LexUnit]:
        article_mode = sum(
            1 for e in elements
            if e.role not in ROLES_SKIPPED and _match_article(e.text.split("\n", 1)[0] if e.text else "")
        ) >= 3

        units: List[LexUnit] = []
        cur: Optional[LexUnit] = None
        chapter = section = ""
        annex_no: Optional[str] = None
        annex_title = ""
        annex_counter = 0
        expecting_annex_title = False
        last_clause_no = 0
        preamble_lines: List[str] = []
        preamble_ids: List[str] = []

        def flush():
            nonlocal cur
            if cur is not None:
                cur.text = cur.text.strip()
                if cur.text or cur.title:
                    if _REPEALED_RE.search(cur.text[:200]) and len(cur.text) < 160:
                        cur.status = "repealed"
                    units.append(cur)
            cur = None

        def attach_amendments(element_id: str):
            notes = amend_after.get(element_id)
            if notes and cur is not None:
                for n in notes:
                    cur.amendments.append(_parse_amendment_note(n))

        for el in elements:
            role, text = el.role, el.text
            if role == ROLE_TITLE or role in ROLES_SKIPPED:
                if role == ROLE_TITLE and not doc.title:
                    doc.title = text
                continue
            if not text:
                continue

            if role in ROLE_ANNEX_BANNER:
                flush()
                annex_counter += 1
                m = _ANNEX_NUM_RE.search(text)
                annex_no = (m.group(1) or m.group(2)) if m else str(annex_counter)
                annex_title = ""
                expecting_annex_title = True
                chapter = section = ""
                last_clause_no = 0
                continue
            if role in ROLE_ANNEX_TITLE:
                annex_title = (annex_title + " " + text).strip() if expecting_annex_title else text
                continue
            expecting_annex_title = False

            if role == ROLE_CHAPTER:
                flush()
                if re.match(r"^(?:\d+|[IVXLC]+)\s*[-–—]?\s*(?:bob|боб)|^глава\s+(?:\d+|[IVXLC]+)", text, re.IGNORECASE):
                    chapter, section = text, ""
                elif re.match(
                    r"^(?:\d+|[IVXLC]+)\s*[-–—]?\s*(?:bo[ʻ'`’‘ʼ]?lim|бўлим)|^раздел\s+(?:\d+|[IVXLC]+)",
                    text, re.IGNORECASE,
                ):
                    section = text
                elif re.match(r"^[IVXLC]+\.\s", text):
                    section = text
                else:
                    chapter = text
                last_clause_no = 0
                continue

            first_line = text.split("\n", 1)[0]
            am = _match_article(first_line)
            if am and (article_mode or role == ROLE_ARTICLE):
                flush()
                number = _article_number(am[0])
                rest = am[1].strip()
                rest_body = text.split("\n", 1)[1] if "\n" in text else ""
                cur = LexUnit(
                    kind="article", number=number, title=rest, text=rest_body,
                    chapter=chapter, section=section, annex_number=annex_no, annex_title=annex_title,
                    element_ids=[el.element_id], tables=el.tables,
                )
                attach_amendments(el.element_id)
                continue

            if not article_mode:
                cm = _CLAUSE_RE.match(first_line)
                if cm:
                    parts = re.split(r"[\^-]", cm.group(1))
                    n = int(parts[0])
                    inserted = len(parts) > 1          # "2-1." / "2^1.": clause 2¹ inserted by a later amendment
                    is_new_context = last_clause_no == 0
                    if is_new_context or n == last_clause_no + 1 or (inserted and n == last_clause_no) or (
                            n == 1 and annex_no is not None and cur is not None and cur.annex_number != annex_no):
                        flush()
                        last_clause_no = n
                        cur = LexUnit(
                            kind="annex_clause" if annex_no else "clause",
                            number=_article_number(cm.group(1)),
                            title="",
                            text=text,
                            chapter=chapter, section=section, annex_number=annex_no, annex_title=annex_title,
                            element_ids=[el.element_id], tables=el.tables,
                        )
                        attach_amendments(el.element_id)
                        continue

            # body paragraph
            if cur is None:
                preamble_lines.append(text)
                preamble_ids.append(el.element_id)
            else:
                cur.text = (cur.text + "\n" + text).strip() if cur.text else text
                cur.element_ids.append(el.element_id)
                cur.tables += el.tables
                attach_amendments(el.element_id)

        flush()

        pre = "\n".join(preamble_lines).strip()
        if len(pre) >= 40:
            units.insert(0, LexUnit(kind="preamble", number="", title="Kirish qismi", text=pre, element_ids=preamble_ids))
        return units

    # ------------------------------------------------------------------------------------------------------
    @staticmethod
    def _transliterate(doc: LexDocument) -> None:
        """Uzbek Cyrillic source -> Latin (the retrieval language of the platform)."""
        doc.title = cyrillic_to_latin(doc.title)
        doc.body = cyrillic_to_latin(doc.body)
        for u in doc.units:
            u.title = cyrillic_to_latin(u.title)
            u.text = cyrillic_to_latin(u.text)
            u.chapter = cyrillic_to_latin(u.chapter)
            u.section = cyrillic_to_latin(u.section)
            u.annex_title = cyrillic_to_latin(u.annex_title)
            for note in u.amendments:
                note.raw = cyrillic_to_latin(note.raw)
        doc.toc_titles = [cyrillic_to_latin(t) for t in doc.toc_titles]

    @staticmethod
    def _qa(doc: LexDocument) -> None:
        if not doc.units:
            doc.warnings.append("no_units_extracted")
            return
        if not doc.number:
            doc.warnings.append("missing_number")
        if not doc.adopted_date:
            doc.warnings.append("missing_date")
        arts = [u for u in doc.units if u.kind == "article" and u.annex_number is None]
        if arts:
            seen: Dict[str, int] = {}
            for u in arts:
                seen[u.number] = seen.get(u.number, 0) + 1
            dup = [n for n, c in seen.items() if c > 1]
            if dup:
                doc.warnings.append(f"duplicate_article_numbers:{','.join(dup[:10])}")
            toc_articles = [t for t in doc.toc_titles if _match_article(_fix_superscripts(t))]
            if toc_articles and abs(len(toc_articles) - len(arts)) > max(2, len(arts) // 10):
                doc.warnings.append(f"toc_mismatch:toc={len(toc_articles)} parsed={len(arts)}")
        empty = [u.display_number for u in doc.units if len(u.text) < 5 and u.status == "active"]
        if empty:
            doc.warnings.append(f"empty_units:{','.join(empty[:10])}")


_ACTION_WORDS = [
    ("tahririda", "tahririda"), ("tahrirda", "tahririda"),
    ("to‘ldirilgan", "to'ldirilgan"), ("toʻldirilgan", "to'ldirilgan"), ("to'ldirilgan", "to'ldirilgan"),
    ("o‘zgartirilgan", "o'zgartirilgan"), ("oʻzgartirilgan", "o'zgartirilgan"), ("o'zgartirilgan", "o'zgartirilgan"),
    ("chiqarib tashlangan", "chiqarib tashlangan"), ("chiqarib tashlandi", "chiqarib tashlangan"),
    ("bekor qilingan", "bekor qilingan"), ("kuchini yo", "kuchini yo'qotgan"),
    ("қўшилган", "to'ldirilgan"), ("ўзгартирилган", "o'zgartirilgan"), ("тахририда", "tahririda"),
]


def _parse_amendment_note(raw: str) -> LexAmendmentNote:
    text = normalize_apostrophes(_norm(raw))
    note = LexAmendmentNote(raw=text)
    note.date = None
    dm = re.search(r"(\d{4})-yil\s+(\d{1,2})-(\w+)", text)
    if dm and dm.group(3).lower() in _UZ_MONTHS:
        note.date = _dmy_to_iso(dm.group(2), str(_UZ_MONTHS[dm.group(3).lower()]), dm.group(1))
    if not note.date:
        note.date = parse_dmy(text)
    nm = re.search(r"((?:O'?RQ|PF|PQ|VMQ|ЎРҚ|ПФ|ПҚ|ВМҚ)\s*[-–—]\s*\d+(?:-[IVX]+)?)", text, re.IGNORECASE)
    if nm:
        note.amending_act = normalize_law_number(nm.group(1))
    low = text.lower()
    for needle, label in _ACTION_WORDS:
        if needle in low:
            note.action = label
            break
    return note

