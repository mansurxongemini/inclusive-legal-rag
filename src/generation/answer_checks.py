"""
Deterministic checks of a generated answer (no LLM, no cost). They catch the failures a judge model tends to wave
through and they run both in the evaluation scripts and, for the cheap ones, on live answers:

* script_ok          - the answer is written in the script of the question (a Cyrillic Uzbek question gets a Cyrillic answer)
* leaked_ids         - internal canonical ids shown to the user instead of [n] markers
* banned_phrases     - wording the prompt forbids ("kontekstda ...", "taqdim etilgan hujjatlar ...")
* ungrounded_numbers - amounts, percentages, terms and dates in the answer that appear neither in the retrieved
                       context nor in the question (a number invented or taken from memory); numbers the sources
                       write in words ("o'n to'rt kun", "тридцать шесть часов") count as present
* uncited_ratio      - share of substantive sentences that carry no [n] citation marker
"""
import re
from typing import Dict, Iterable, List, Optional, Sequence

_CYR = re.compile(r"[А-Яа-яЁёЎўҒғҚқҲҳ]")
_LAT = re.compile(r"[A-Za-z]")
_MARKER = re.compile(r"\[\d+(?:\s*[,;-]\s*\d+)*\]")
_NUMBER = re.compile(r"\d+(?:[   ]\d{3})*(?:[.,]\d+)?")
_ID_LIKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}\b")
_BRACKET_ID = re.compile(r"\[[A-Za-z0-9_\-]*_[A-Za-z0-9_\-]+(?:\s*[,;]\s*[A-Za-z0-9_\-]*_[A-Za-z0-9_\-]+)*\]")
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


# Numbers written in words. Uzbek statutes write most terms that way ("o'n to'rt kalendar kungacha", "o'ttiz olti
# soatdan"), and an answer that writes them as digits is quoting, not inventing.
_UZ_NUMBER_WORDS = {
    "bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "besh": 5, "olti": 6, "yetti": 7, "sakkiz": 8, "to'qqiz": 9,
    "o'n": 10, "yigirma": 20, "o'ttiz": 30, "qirq": 40, "ellik": 50, "oltmish": 60, "yetmish": 70, "sakson": 80,
    "to'qson": 90, "yuz": 100, "ming": 1000,
    "бир": 1, "икки": 2, "уч": 3, "тўрт": 4, "беш": 5, "олти": 6, "етти": 7, "саккиз": 8, "тўққиз": 9,
    "ўн": 10, "йигирма": 20, "ўттиз": 30, "қирқ": 40, "эллик": 50, "олтмиш": 60, "етмиш": 70, "саксон": 80,
    "тўқсон": 90, "юз": 100, "минг": 1000,
}
# a case or ordinal ending after the last word: "o'n oltiga", "uchinchi", "ўттиздан" ("uchun" is not one)
_UZ_SUFFIX = re.compile(r"^(?:inchi|nchi|ta|tasi|ga|ka|qa|da|dan|ni|ning|gacha|lik|лик|инчи|нчи|та|таси|га|ка|қа|да|"
                        r"дан|ни|нинг|гача)?$")
# "yuz" is also "face" ("zarar yuz bergan" = damage occurred): it is a number only next to another number word or before
# a counted noun
_UZ_HUNDRED = {"yuz", "юз"}
_COUNTED_AFTER_HUNDRED = re.compile(r"^(?:foiz|ming|million|so'm|nafar|kun|soat|yil|marta|kishi|baravar|ta|фоиз|минг|"
                                    r"сўм|нафар|кун|соат|йил|марта|киши|баравар|та)", re.IGNORECASE)
# Russian number words as whole forms (a stem such as "сто" or "сем" also starts "стороны" or "семьи")
_RU_NUMBER_FORMS: Dict[str, int] = {}
for _value, _forms in (
    (1, "один одна одно одного одной одному одним одном одну"), (2, "два две двух двум двумя"),
    (3, "три трех трёх трем трём тремя"), (4, "четыре четырех четырёх четырем четырём четырьмя"),
    (5, "пять пяти пятью"), (6, "шесть шести шестью"), (7, "семь семи семью"), (8, "восемь восьми восемью восьмью"),
    (9, "девять девяти девятью"), (10, "десять десяти десятью"), (11, "одиннадцать одиннадцати"),
    (12, "двенадцать двенадцати"), (13, "тринадцать тринадцати"), (14, "четырнадцать четырнадцати"),
    (15, "пятнадцать пятнадцати"), (16, "шестнадцать шестнадцати"), (17, "семнадцать семнадцати"),
    (18, "восемнадцать восемнадцати"), (19, "девятнадцать девятнадцати"), (20, "двадцать двадцати двадцатью"),
    (30, "тридцать тридцати тридцатью"), (40, "сорок сорока"), (50, "пятьдесят пятидесяти пятьюдесятью"),
    (60, "шестьдесят шестидесяти"), (70, "семьдесят семидесяти"), (80, "восемьдесят восьмидесяти"),
    (90, "девяносто девяноста"), (100, "сто ста"), (200, "двести двухсот двумстам"), (300, "триста трехсот трёхсот"),
    (400, "четыреста четырехсот четырёхсот"), (500, "пятьсот пятисот"), (600, "шестьсот шестисот"),
    (700, "семьсот семисот"), (800, "восемьсот восьмисот"), (900, "девятьсот девятисот"),
    (1000, "тысяча тысячи тысяч тысячу тысячей"),
):
    for _form in _forms.split():
        _RU_NUMBER_FORMS[_form] = _value
_WORD = re.compile(r"[^\W\d_][\w'ʻʼ‘’]*", re.UNICODE)


def _word_value(token: str) -> Optional[int]:
    t = re.sub(r"[ʻʼ‘’`]", "'", token.lower())
    if t in _RU_NUMBER_FORMS:
        return _RU_NUMBER_FORMS[t]
    for word, value in _UZ_NUMBER_WORDS.items():
        if t.startswith(word) and _UZ_SUFFIX.match(t[len(word):]):
            return value
    return None


def number_words(text: str) -> List[str]:
    """Numbers written in Uzbek (Latin or Cyrillic) or Russian words, as digit strings: "o'n to'rt" -> "14".
    A number is a run of number words separated by spaces only: "o'n besh, yigirma kun" is 15 and 20, not 35."""
    text = text or ""
    tokens = list(_WORD.finditer(text))
    values = [_word_value(m.group(0)) for m in tokens]
    for i, m in enumerate(tokens):                        # "yuz" counts only next to a number or before a counted noun
        if values[i] == 100 and m.group(0).lower() in _UZ_HUNDRED:
            prev_num = i > 0 and values[i - 1] is not None and not text[tokens[i - 1].end(): m.start()].strip()
            nxt = text[m.end():].lstrip()
            next_num = i + 1 < len(tokens) and values[i + 1] is not None and not text[m.end(): tokens[i + 1].start()].strip()
            if not (prev_num or next_num or _COUNTED_AFTER_HUNDRED.match(nxt)):
                values[i] = None
    out: List[str] = []
    total = current = 0
    started = False
    prev_end = None

    def flush():
        nonlocal total, current, started
        if started and total + current:
            out.append(str(total + current))
        total = current = 0
        started = False

    for m, value in zip(tokens, values):
        if value is None or (prev_end is not None and text[prev_end: m.start()].strip()):
            flush()                                       # a comma, hyphen or other word ends the number
        prev_end = m.end()
        if value is None:
            continue
        started = True
        if value == 100:
            current = (current or 1) * 100
        elif value == 1000:
            total += (current or 1) * 1000
            current = 0
        else:
            current += value
    flush()
    return out


# "yetti soatu o'ttiz daqiqa" is quoted as "7.5 hours" by a faithful answer: hours and minutes also count as a decimal
_HOURS_MINUTES = re.compile(
    r"([^\W_][\w'ʻʼ‘’]*|\d+)\s+(?:soat|soatu|soati|час|часа|часов|hours?)\s+(?:va\s+|и\s+|and\s+)?"
    r"([^\W_][\w'ʻʼ‘’]*|\d+)\s+(?:daqiqa|минут|minutes?)", re.IGNORECASE)


def _as_int(token: str) -> Optional[int]:
    if token.isdigit():
        return int(token)
    return _word_value(token)


def hours_as_decimals(text: str) -> List[str]:
    """Digit strings of "H soat M daqiqa" written as a decimal number of hours: 7 h 30 min -> "75" (7.5)."""
    out = []
    for h, m in _HOURS_MINUTES.findall(text or ""):
        hours, minutes = _as_int(h), _as_int(m)
        if hours is not None and minutes and 0 < minutes < 60:
            decimal = f"{hours + minutes / 60:.2f}".rstrip("0").rstrip(".")
            out.append(_digits(decimal))
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
        exact.update(number_words(text))
        exact.update(hours_as_decimals(text))
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
