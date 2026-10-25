"""
Repeal notices: when a question names an act that a unit of the corpus repealed ("Vazirlar Mahkamasining 2021-yil
29-apreldagi 257-son qarori o'z kuchini yo'qotgan deb hisoblansin"), that unit is put in front of the contexts, so the
answer starts from the fact that the act lost force instead of describing it as current law.

Ranking alone found the repeal clause only at the edge of the contexts (rank 8 of 8) and lost it as soon as the corpus
grew. Matching is strict, because a wrong notice would declare a law in force repealed: the act number must match, the
question must name the year of the repealed act, and a type the question names (a Cabinet resolution, a Presidential
resolution or decree, a law) must be the type of that act.
"""
import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

# the operative repeal sentence, not the title of an amending act ("... ba'zilarini o'z kuchini yo'qotgan deb hisoblash
# to'g'risida" is a title)
_OPERATIVE = re.compile(r"o['ʻ’‘ʼ`]?z\s+kuchini\s+yo['ʻ’‘ʼ`]?qotgan\s+deb\s+(?:hisoblansin|topilsin)", re.IGNORECASE)
_LIST_HEAD = re.compile(r"^\s*Quyidagilar\s+o['ʻ’‘ʼ`]?z\s+kuchini\s+yo['ʻ’‘ʼ`]?qotgan\s+deb\s+(?:hisoblansin|topilsin)",
                        re.IGNORECASE)
_ACT_IN_TEXT = re.compile(
    r"(?P<pq>\bPQ\s*[-–]\s*(?P<pqn>\d{1,5}))|(?P<pf>\bPF\s*[-–]\s*(?P<pfn>\d{1,5}))|"
    r"(?P<old>\b(?P<oldn>\d{2,4}-[IVX]{1,4})\b)|(?P<son>\b(?P<sonn>\d{1,5})-son(?:li)?\b)",
)
_YEAR_UZ = re.compile(r"\b(19\d{2}|20\d{2})-yil")


@dataclass(frozen=True)
class RepealedAct:
    number: str
    kind: str            # vmq | pq | pf | law | ""
    year: str            # "" when the sentence names none
    canonical_id: str
    points: frozenset = frozenset()     # empty: the whole act; else the numbers of the repealed points / items


# what may stand between the act number and the end of the repeal: nothing of the act's content ("257-son qarori",
# "422-XII-sonli Qonuni (... Axborotnomasi, 1992-yil, № 2, 78-modda)"); anything else ("qarorining 1 va 2-bandlari",
# "qarori bilan tasdiqlangan Nizomning 25-bandi") makes the repeal partial
_WHOLE = re.compile(
    r"[\s\-]*(?:sonli|son)?\s*(?:qarori|farmoni|qonuni|farmoyishi|buyrug['ʻ’‘ʼ`]?i)?\s*(?:\([^)]*\))?[\s,;]*",
    re.IGNORECASE)


def _kind_before(text: str, start: int) -> str:
    window = text[max(0, start - 300): start].lower()
    tail = text[start: start + 40].lower()
    if "qonun" in tail or "qonuni" in window[-60:]:
        return "law"
    pos = {k: window.rfind(w) for k, w in (("vmq", "vazirlar mahkamasi"), ("pres", "prezident"))}
    if pos["vmq"] < 0 and pos["pres"] < 0:
        return ""
    if pos["vmq"] > pos["pres"]:
        return "vmq"
    return "pf" if "farmon" in tail else "pq"


def _acts_in(sentence: str, cid: str) -> List[RepealedAct]:
    """Acts named in `sentence` (the part of a repeal before its operative phrase, or one item of a repeal list)."""
    out = []
    matches = list(_ACT_IN_TEXT.finditer(sentence))
    for i, m in enumerate(matches):
        years = _YEAR_UZ.findall(sentence[max(0, m.start() - 160): m.start()])
        year = years[-1] if years else ""
        tail = sentence[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(sentence)]
        tail = re.sub(r"“[^”]*”|\"[^\"]*\"", " ", tail)
        points = frozenset() if _WHOLE.fullmatch(tail) else frozenset(re.findall(r"\b(\d{1,3})\b", tail)) or frozenset({"?"})
        if m.group("pq"):
            out.append(RepealedAct(m.group("pqn"), "pq", year, cid, points))
        elif m.group("pf"):
            out.append(RepealedAct(m.group("pfn"), "pf", year, cid, points))
        elif m.group("old"):
            out.append(RepealedAct(m.group("oldn").upper(), "law", year, cid, points))
        else:
            out.append(RepealedAct(m.group("sonn"), _kind_before(sentence, m.start()), year, cid, points))
    return out


def build_index(rows) -> Dict[str, List[RepealedAct]]:
    """rows: (canonical_id, uz_text). {act number: acts repealed by some unit}."""
    index: Dict[str, List[RepealedAct]] = {}
    for cid, text in rows:
        if not text or "kuchini" not in text:
            continue
        if _LIST_HEAD.search(text):                              # "Quyidagilar o'z kuchini yo'qotgan deb topilsin: 1) ..."
            sentences = [item for item in re.split(r"\n|;\s*(?=\d+\)\s)", _LIST_HEAD.sub("", text)) if item.strip()]
        else:
            sentences = [s for s in re.split(r"(?<=[.;])\s+(?=[A-ZА-ЯЎҚҒҲ“\"0-9])", text) if _OPERATIVE.search(s)]
        for sentence in sentences:
            cut = _OPERATIVE.search(sentence)
            sentence = sentence[: cut.start()] if cut else sentence        # acts named before the operative phrase
            for act in _acts_in(sentence, cid):
                index.setdefault(act.number, []).append(act)
    return index


# --- the question ---------------------------------------------------------------------------------------------------
_Q_NUMBER = re.compile(
    r"(?:\b(?:VMQ|PQ|PF|ПКМ|ПП|УП|O['ʻ’‘ʼ`]?RQ|ЗРУ)\s*[-–]?\s*(\d{1,5}))|(?:\b(\d{1,5})\s*-\s*(?:son|сон)\b)|"
    r"(?:№\s*(\d{1,5}))|(?:\bNo\.?\s*(\d{1,5}))|(?:\b(\d{2,4}-[IVX]{1,4})\b)",
    re.IGNORECASE,
)
_Q_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")


def question_kind(question: str) -> str:
    q = question.lower()
    if re.search(r"\b(?:vmq|пкм)\b|vazirlar mahkamasi|кабинет\w* министров|cabinet of ministers|hukumat qarori", q):
        return "vmq"
    if re.search(r"\b(?:pf|уп)\s*[-–]|farmon|указ|decree", q):
        return "pf"
    if re.search(r"\b(?:pq|пп)\s*[-–]|prezident\w* qarori|постановлени\w* президента|presidential resolution", q):
        return "pq"
    if re.search(r"o['ʻ’‘ʼ`]?rq|зру|\bqonun|\bзакон|\blaw\b", q):
        return "law"
    return ""


def matching_acts(question: str, index: Dict[str, List[RepealedAct]]) -> List[RepealedAct]:
    numbers = {next(g for g in m.groups() if g).upper() for m in _Q_NUMBER.finditer(question or "")}
    if not numbers:
        return []
    years: Set[str] = set(_Q_YEAR.findall(question))
    if not years:
        return []        # "VMQ-62" alone: the repealed 62-son of 1995 is not the 62-son of 2022 that is in force
    kind = question_kind(question)
    found = []
    # a partial repeal (some points of the act) is a notice only for a question about those points
    asks_points = bool(re.search(r"band|пункт|item|point|paragraph|clause", question, re.IGNORECASE))
    question_ints = set(re.findall(r"\b(\d{1,3})\b", question))
    for n in numbers:
        for act in index.get(n, []):
            if act.year not in years:
                continue
            if act.kind and kind and act.kind != kind:
                continue
            if act.points and not (asks_points and act.points & question_ints):
                continue
            found.append(act)
    return found


_INDEX_ATTR = "_repeal_index"


def _store_index(store) -> Dict[str, List[RepealedAct]]:
    fts = store.fts_store
    index = getattr(fts, _INDEX_ATTR, None)
    if index is None:
        with fts._get_connection() as conn:
            rows = [(cid, (json.loads(raw).get("translations") or {}).get("uz") or "")
                    for cid, raw in conn.execute("SELECT canonical_id, json_data FROM articles_metadata "
                                                 "WHERE json_data LIKE '%kuchini%'")]
        index = build_index(rows)
        setattr(fts, _INDEX_ATTR, index)
    return index


def repeal_notices(question: str, store, exclude: Optional[Set[str]] = None, limit: int = 2) -> list:
    """Units of the store that repealed an act the question names (strict match), as CanonicalArticle objects."""
    try:
        acts = matching_acts(question, _store_index(store))
    except Exception:
        return []
    ids: List[str] = []
    for act in acts:
        if act.canonical_id not in ids and act.canonical_id not in (exclude or set()):
            ids.append(act.canonical_id)
    found = store.get_articles_batch(ids[:limit]) if ids else {}
    return [found[c] for c in ids[:limit] if c in found]
