"""
Deterministic checks of a generated answer (no LLM, no cost). They catch the failures a judge model tends to wave
through and they run both in the evaluation scripts and, for the cheap ones, on live answers:

* script_ok          - the answer is written in the script of the question (a Cyrillic Uzbek question gets a Cyrillic answer)
* leaked_ids         - internal canonical ids shown to the user instead of [n] markers
* banned_phrases     - wording the prompt forbids ("kontekstda ...", "taqdim etilgan hujjatlar ...")
* ungrounded_numbers - amounts, percentages, terms and dates in the answer that appear neither in the retrieved
                       context nor in the question (a number invented or taken from memory)
* uncited_ratio      - share of substantive sentences that carry no [n] citation marker
"""
import re
from typing import Dict, Iterable, List, Optional, Sequence

_CYR = re.compile(r"[А-Яа-яЁёЎўҒғҚқҲҳ]")
_LAT = re.compile(r"[A-Za-z]")
_MARKER = re.compile(r"\[\d+(?:\s*[,;-]\s*\d+)*\]")
_NUMBER = re.compile(r"\d+(?:[   ]\d{3})*(?:[.,]\d+)?")
_ID_LIKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}\b")
_BRACKET_ID = re.compile(r"\[[A-Za-z0-9_\-]*_[A-Za-z0-9_\-]+\]")
_SENTENCE = re.compile(r"(?<=[.!?\]])\s+|\n+")

BANNED = (
    "kontekstda", "kontekstga ko'ra", "taqdim etilgan hujjat", "taqdim etilgan kontekst", "siz keltirgan hujjat",
    "в контексте", "в предоставленном", "предоставленных документах", "retrieved context", "provided context",
    "as an ai", "men sun'iy intellekt",
)


def _letters(text: str) -> str:
    return _MARKER.sub("", text or "")


def script_share(text: str) -> Dict[str, float]:
    """Share of Cyrillic and Latin letters among all letters (citation markers excluded)."""
    t = _letters(text)
    cyr, lat = len(_CYR.findall(t)), len(_LAT.findall(t))
    total = cyr + lat
    return {"cyrillic": cyr / total if total else 0.0, "latin": lat / total if total else 0.0}


def script_ok(question: str, answer: str, language: Optional[str] = None, threshold: float = 0.7) -> bool:
    """The answer uses the question's script: Cyrillic question -> Cyrillic answer, otherwise Latin."""
    asked = script_share(question)
    if not (asked["cyrillic"] + asked["latin"]):
        return True
    shares = script_share(answer)
    if not (shares["cyrillic"] + shares["latin"]):
        return True
    want = "cyrillic" if asked["cyrillic"] > asked["latin"] else "latin"
    if language == "en":
        want = "latin"
    return shares[want] >= threshold


def leaked_ids(answer: str, known_ids: Iterable[str] = ()) -> List[str]:
    """Internal ids visible in the answer text (known context ids, or anything shaped like a canonical id)."""
    found = {cid for cid in known_ids if cid and cid in answer}
    found.update(m for m in _ID_LIKE.findall(answer) if re.search(r"\d", m))
    return sorted(found)


def banned_phrases(answer: str) -> List[str]:
    low = (answer or "").lower().replace("‘", "'").replace("’", "'").replace("ʻ", "'").replace("ʼ", "'")
    return [p for p in BANNED if p in low]


def _digits(token: str) -> str:
    return re.sub(r"\D", "", token)


def numbers_in(text: str, min_digits: int = 2) -> List[str]:
    """Numbers of a text as digit strings ('1 500 000' -> '1500000', '0,5' -> '05'); one-digit numbers are ignored."""
    out = []
    for m in _NUMBER.finditer(_BRACKET_ID.sub(" ", _MARKER.sub(" ", text or ""))):
        d = _digits(m.group(0))
        if len(d) >= min_digits:
            out.append(d)
    return out


def _loose(digits: str) -> str:
    """'1500000', '1,5 mln' and '15' share one loose form: trailing zeros do not tell amounts apart in a rewording."""
    return digits.rstrip("0") or "0"


def ungrounded_numbers(answer: str, context_texts: Sequence[str], question: str = "") -> List[str]:
    """Numbers (two digits or more) of the answer that occur in neither the retrieved texts nor the question."""
    exact, loose = set(), set()
    for text in list(context_texts) + [question]:
        for n in numbers_in(text, min_digits=1):
            exact.add(n)
            if len(n) >= 3:                      # short numbers are not loosened: "2" must not excuse "2 000 000"
                loose.add(_loose(n))
    # list numbering at the start of a line ("1." "2)") is structure, not a claim
    body = re.sub(r"(?m)^\s*\d+[.)]\s+", "", answer or "")
    return sorted({n for n in numbers_in(body) if n not in exact and _loose(n) not in loose})


def uncited_ratio(answer: str, min_words: int = 6) -> float:
    """Share of substantive sentences (at least `min_words` words, no heading) without a [n] marker."""
    glued = re.sub(r"\s+(\[\d+(?:\s*[,;-]\s*\d+)*\])", r"\1", answer or "")        # "text. [1]" -> "text.[1]"
    sentences = [s.strip() for s in _SENTENCE.split(glued) if s and s.strip()]
    substantive = [s for s in sentences if len(s.split()) >= min_words and not s.lstrip().startswith(("#", "*", "-"))
                   or (s.lstrip().startswith(("*", "-")) and len(s.split()) >= min_words)]
    if not substantive:
        return 0.0
    return sum(1 for s in substantive if not _MARKER.search(s)) / len(substantive)


def strip_disclaimer(answer: str) -> str:
    """The answer without the appended disclaimer block ('---' rule and everything after it)."""
    return re.split(r"\n\s*---", answer or "", maxsplit=1)[0].strip()


def check_answer(question: str, answer: str, context_texts: Sequence[str], known_ids: Iterable[str] = (),
                 language: Optional[str] = None) -> Dict:
    """All deterministic checks in one record (stored per item in the evaluation reports)."""
    answer = strip_disclaimer(answer)
    return {
        "script_ok": script_ok(question, answer, language),
        "leaked_ids": leaked_ids(answer, known_ids),
        "banned_phrases": banned_phrases(answer),
        "ungrounded_numbers": ungrounded_numbers(answer, context_texts, question),
        "uncited_ratio": round(uncited_ratio(answer), 3),
    }
