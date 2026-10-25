"""
Quality checks of stored units (scripts/audit_corpus.py runs them over the whole store).

Hard problems make a unit wrong for a reader: no Uzbek text, a broken character (U+FFFD), HTML left in the text, a source
link that is not a Lex.uz document. Soft ones are kept as a report: the next chapter's heading glued to the end of a point,
a point whose text swallowed later points that have no unit of their own (see BLOCKERS.md).
"""
import re
from typing import Dict, Iterable, List, Set

_HTML = re.compile(r"</?(?:p|div|span|br|a|table|td|tr)\b|&nbsp;|&amp;|&quot;", re.I)
_LEX_URL = re.compile(r"^https://(?:www\.)?lex\.uz/(?:uz/|ru/)?docs/-?\d+")
_HEADING_LINE = re.compile(
    r"^(?:\d+(?:\.\d+)?-(?:bob|§|bo'lim|paragraf)\b.*|[IVXLC]+\.\s+\S.*|NIZOM|TARTIB|RO'YXAT|REGLAMENT|YO'RIQNOMA|QOIDALAR)$")
_POINT_ID = re.compile(r"^(.*_p_)(\d+)$")


def hard_problems(cid: str, uz_text: str, source_url: str, source_type: str) -> List[str]:
    problems = []
    if not (uz_text or "").strip():
        problems.append("no_uzbek_text")
    if "�" in (uz_text or ""):
        problems.append("broken_character")
    if _HTML.search(uz_text or ""):
        problems.append("html_in_text")
    if source_type in ("lex", None, "") and not _LEX_URL.match(source_url or ""):
        problems.append("not_a_lex_link")
    return problems


def glued_heading(uz_text: str) -> str:
    """The last line when it is a heading of the next section ("3-bob. ...", "III. ...", "NIZOM"), else ''."""
    text = (uz_text or "").rstrip()
    if "\n" not in text:
        return ""
    last = text.rsplit("\n", 1)[1].strip()
    return last if 0 < len(last) <= 140 and _HEADING_LINE.match(last) else ""


def swallowed_points(cid: str, uz_text: str, existing_ids: Set[str]) -> List[int]:
    """Numbers of later points written inside this point's text whose own units do not exist."""
    m = _POINT_ID.match(cid)
    if not m:
        return []
    base, n = m.group(1), int(m.group(2))
    found = [k for k in range(n + 1, n + 30)
             if re.search(rf"(?:^|[\s.;:]){k}\.\s+[A-ZА-ЯЎҚҒҲ“\"«]", uz_text or "")]
    return [k for k in found if f"{base}{k}" not in existing_ids]


def audit(units: Iterable[tuple]) -> Dict:
    """units: (canonical_id, uz_text, source_url, source_type[, ru_text]). Returns counts and examples per problem."""
    from src.ingestion.translation_alignment import split_russian_overflow
    units = list(units)
    ids = {u[0] for u in units}
    by_base: Dict[str, dict] = {}
    for u in units:
        m = _POINT_ID.match(u[0])
        if m and len(u) > 4:
            by_base.setdefault(m.group(1), {})[u[0]] = (u[1], u[4] or "")
    # a Russian text that still holds later points whose units have no Russian text of their own
    overflow = sorted(c for group in by_base.values() for c in split_russian_overflow(group))
    hard: Dict[str, List[str]] = {}
    glued, swallowed = [], []
    for cid, text, url, stype, *_ru in units:
        for p in hard_problems(cid, text, url, stype):
            hard.setdefault(p, []).append(cid)
        if glued_heading(text):
            glued.append(cid)
        if swallowed_points(cid, text, ids):
            swallowed.append(cid)
    return {
        "units": len(units),
        "hard": {k: {"count": len(v), "examples": v[:10]} for k, v in hard.items()},
        "glued_headings": {"count": len(glued), "examples": glued[:10]},
        "swallowed_points": {"count": len(swallowed), "examples": swallowed[:10]},
        "russian_overflow": {"count": len(overflow), "examples": overflow[:10]},
    }
