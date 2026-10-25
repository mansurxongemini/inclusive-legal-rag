"""
Repeal notices: when a question names an act that a unit of the corpus repealed ("Vazirlar Mahkamasining 2021-yil
29-apreldagi 257-son qarori o'z kuchini yo'qotgan deb hisoblansin"), that unit is put in front of the contexts, so the
answer starts from the fact that the act lost force instead of describing it as current law.

Ranking alone found the repeal clause only at the edge of the contexts (rank 8 of 8) and lost it as soon as the corpus
grew. Matching is strict, because a wrong notice would declare a law in force repealed: the question must name the act's
type (a Cabinet resolution, a Presidential resolution or decree, a law) and it must be the repealed act's type, the act
number and the year must match, and a partial repeal ("... qarorining 1 va 2-bandlari", "... 5-ilova") is a notice only
for a question about those points or annexes.
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
# items of an amending act: "...62-son qarorida: a) 2-band ... tahrirda bayon etilsin; g) 5-ilova o'z kuchini yo'qotgan"
# - only the last item before the operative phrase is what lost force
_ITEM_BREAK = re.compile(r"[;\n]|:\s|\s[a-zа-я]\)\s")
_POINTS = re.compile(r"((?:\d{1,3}\s*(?:,|va|—|–)\s*)*\d{1,3})\s*-\s*(band|ilova)", re.IGNORECASE)


@dataclass(frozen=True)
class RepealedAct:
    number: str
    kind: str            # vmq | pq | pf | law | ""
    year: str            # "" when the sentence names none
    canonical_id: str
    points: frozenset = frozenset()     # empty: the whole act; else {"band:1", "ilova:5", ...} that lost force


# what may stand between the act number and the end of the repeal: nothing of the act's content ("257-son qarori",
# "422-XII-sonli Qonuni (... Axborotnomasi, 1992-yil, № 2, 78-modda)"); anything else makes the repeal partial
_WHOLE = re.compile(
    r"[\s\-]*(?:sonli|son)?\s*(?:qarori|farmoni|qonuni|farmoyishi|buyrug['ʻ’‘ʼ`]?i)?\s*(?:\([^)]*\))?[\s,;]*",
    re.IGNORECASE)


def _points_in(text: str) -> frozenset:
    found = set()
    for numbers, kind in _POINTS.findall(text):
        for n in re.findall(r"\d{1,3}", numbers):
            found.add(f"{kind.lower()}:{n}")
    return frozenset(found)


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
    """Acts repealed by `sentence` (the text before an operative phrase, or one item of a repeal list)."""
    sentence = sentence.rstrip(" ;,.\n")                     # "...-sonli Qonuni (...);": no empty last item
    pieces = _ITEM_BREAK.split(sentence)
    last_start = len(sentence) - len(pieces[-1])            # the item the operative phrase applies to
    out = []
    matches = list(_ACT_IN_TEXT.finditer(sentence))
    for i, m in enumerate(matches):
        prev_end = matches[i - 1].end() if i else 0
        years = _YEAR_UZ.findall(sentence[prev_end: m.start()])    # the year written with this act, however long its title
        year = years[-1] if years else ""
        if m.start() >= last_start:
            tail = sentence[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(sentence)]
            tail = re.sub(r"“[^”]*”|\"[^\"]*\"", " ", tail)
            points = frozenset() if _WHOLE.fullmatch(tail) else (_points_in(tail) or frozenset({"?"}))
        else:
            # the act is named before the item that lost force ("62-son qarorida: ... g) 5-ilova"): only that item
            points = _points_in(pieces[-1]) or frozenset({"?"})
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
    r"(?:\b(?:VMQ|PQ|PF|ПКМ|ПП|УП|O['ʻ’‘ʼ`]?RQ|ЗРУ)\s*[-–]?\s*(\d{1,5}))|(?:\b(\d{1,5})\s*-\s*(?:son|сон)(?:li|ли)?\b)|"
    r"(?:№\s*(\d{1,5}(?:-[IVX]{1,4})?))|(?:\bNo\.?\s*(\d{1,5}(?:-[IVX]{1,4})?))|(?:\b(\d{2,4}-[IVX]{1,4})\b)",
    re.IGNORECASE,
)
_Q_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
_Q_POINTS_UZ = re.compile(r"((?:\d{1,3}\s*(?:,|va|и|and)\s*)*\d{1,3})\s*-?\s*(band|ilova|банд|илова)", re.IGNORECASE)
_Q_POINTS_OTHER = re.compile(
    r"(пункт|приложени|items?|points?|paragraphs?|clauses?|annex(?:es)?)\w*\s*(?:№\s*)?((?:\d{1,3}\s*(?:,|и|and|va)\s*)*\d{1,3})",
    re.IGNORECASE)


def question_kind(question: str) -> str:
    q = question.lower()
    if re.search(r"\b(?:vmq|пкм)\b|vazirlar\s+mahkamasi|вазирлар\s+маҳкамаси|кабинет\w*\s+министров|cabinet of ministers|"
                 r"hukumat qarori", q):
        return "vmq"
    if re.search(r"\b(?:pf|уп)\s*[-–]|farmon|фармон|указ|decree", q):
        return "pf"
    if re.search(r"\b(?:pq|пп)\s*[-–]|prezident\w*[^.?!]{0,80}qaror|президент\w*[^.?!]{0,80}(?:қарор|постановлени)|"
                 r"presidential resolution|resolution of the president", q):
        return "pq"
    if re.search(r"o['ʻ’‘ʼ`]?rq|ўрқ|зру|\bqonun|\bқонун|\bзакон|\blaw\b", q):
        return "law"
    return ""


def question_points(question: str) -> Set[str]:
    found = set()
    for numbers, kind in _Q_POINTS_UZ.findall(question):
        k = "ilova" if kind.lower() in ("ilova", "илова") else "band"
        found |= {f"{k}:{n}" for n in re.findall(r"\d{1,3}", numbers)}
    for kind, numbers in _Q_POINTS_OTHER.findall(question):
        k = "ilova" if kind.lower().startswith(("приложени", "annex")) else "band"
        found |= {f"{k}:{n}" for n in re.findall(r"\d{1,3}", numbers)}
    return found


def matching_acts(question: str, index: Dict[str, List[RepealedAct]]) -> List[RepealedAct]:
    numbers = {next(g for g in m.groups() if g).upper() for m in _Q_NUMBER.finditer(question or "")}
    if not numbers:
        return []
    years: Set[str] = set(_Q_YEAR.findall(question))
    kind = question_kind(question)
    if not years or not kind:
        return []        # "VMQ-62" alone: the repealed 62-son of 1995 is not the 62-son of 2022 that is in force
    asked_points = question_points(question)
    found = []
    for n in numbers:
        for act in index.get(n, []):
            if act.year not in years or act.kind != kind:
                continue
            if act.points and not (act.points & asked_points):
                continue                     # a partial repeal concerns only the question about those points
            found.append(act)
    return found


_INDEX_ATTR = "_repeal_index"
_GEN_ATTR = "_repeal_gen"


def invalidate(fts) -> None:
    """Called by the store on every write: the next question rebuilds the index."""
    fts.__dict__[_GEN_ATTR] = fts.__dict__.get(_GEN_ATTR, 0) + 1
    fts.__dict__.pop(_INDEX_ATTR, None)


def _store_index(store) -> Dict[str, List[RepealedAct]]:
    fts = store.fts_store
    index = fts.__dict__.get(_INDEX_ATTR)
    if index is None:
        generation = fts.__dict__.get(_GEN_ATTR, 0)
        with fts._get_connection() as conn:
            rows = [(cid, (json.loads(raw).get("translations") or {}).get("uz") or "")
                    for cid, raw in conn.execute("SELECT canonical_id, json_data FROM articles_metadata "
                                                 "WHERE json_data LIKE '%kuchini%'")]
        index = build_index(rows)
        if fts.__dict__.get(_GEN_ATTR, 0) == generation:      # a write during the build makes this index stale
            fts.__dict__[_INDEX_ATTR] = index
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
