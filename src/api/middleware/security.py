import re
import logging
import unicodedata
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Prompt injection patterns. Non-English ones only match imperative forms ("forget the previous rules"), so
# ordinary legal questions such as "avvalgi qoidalar bekor qilinganmi?" are not blocked.
_APOS = "['\u02bb\u02bc\u2018\u2019`\u00b4]?"
_UZ_LAT_PRIOR = r"(?:oldingi|avvalgi|yuqoridagi|barcha)\s+(?:barcha\s+)?(?:ko{a}rsatma|yo{a}riqnoma|qoida|buyruq|prompt)\w*".format(a=_APOS)
_UZ_LAT_IGNORE = r"(?:unut(?:ing|ingiz|inglar|gin)?|bekor\s+qil(?:ing|ingiz|inglar|gin)?|rad\s+et(?:ing|ingiz|inglar|gin)?|e{a}tibor(?:ga)?\s+(?:berma|olma)(?:ng|ngiz|nglar|gin)|e{a}tiborsiz\s+qoldir(?:ing|ingiz|inglar|gin)?)\b".format(a=_APOS)
_UZ_CYR_PRIOR = r"(?:олдинги|аввалги|юқоридаги|барча)\s+(?:барча\s+)?(?:кўрсатма|йўриқнома|қоида|буйруқ|промпт)\w*"
_UZ_CYR_IGNORE = r"(?:унут(?:инг|ингиз|инглар|гин)?|бекор\s+қил(?:инг|ингиз|инглар|гин)?|рад\s+эт(?:инг|ингиз|инглар|гин)?|эътибор(?:га)?\s+(?:берма|олма)(?:нг|нгиз|нглар|гин)|эътиборсиз\s+қолдир(?:инг|ингиз|инглар|гин)?)\b"
_RU_PRIOR = r"(?:все\s+|любые\s+|всю\s+)?(?:предыдущ|прежн|прошл|вышестоящ)\w*\s+(?:инструкци|указани|правил|команд|промпт)\w*"

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"forget\s+(all\s+)?(previous|prior)\s+instructions",
    r"(?:ignore|disregard|forget|override|discard)\s+(?:all\s+|any\s+)?(?:the\s+|your\s+)?(?:previous|prior|earlier|above|preceding|former)\s+(?:instructions?|rules|guidelines|prompts?|directions)",
    r"(?:reveal|show|print|repeat|display)\s+(?:me\s+)?(?:your\s+|the\s+)?system\s*prompt",
    r"system\s*prompt\s*override",
    r"you\s+are\s+now\s+dan",
    r"bypass\s+rules",
    r"jailbreak",
    r"you\s+must\s+act\s+as\s+unfiltered",
    # Uzbek (Latin): "oldingi ko'rsatmalarni unuting", "barcha qoidalarga e'tibor bermang", "system promptni ko'rsat"
    rf"{_UZ_LAT_PRIOR}\s+{_UZ_LAT_IGNORE}",
    rf"{_UZ_LAT_IGNORE}\s+{_UZ_LAT_PRIOR}",
    rf"(?:system\s*prompt|tizim\s+prompt|tizim\s+ko{_APOS}rsatma)\w*\s+(?:ni\s+)?(?:ko{_APOS}rsat|ayt|chop\s+et|chiqar|oshkor)\w*",
    r"(?:cheklovsiz|cheklovlarsiz|filtrsiz)\s+(?:rejim|rol)\w*",
    # Uzbek (Cyrillic)
    rf"{_UZ_CYR_PRIOR}\s+{_UZ_CYR_IGNORE}",
    rf"{_UZ_CYR_IGNORE}\s+{_UZ_CYR_PRIOR}",
    r"(?:system\s*prompt|тизим\s+промпт)\w*\s+(?:ни\s+)?(?:кўрсат|айт|чоп\s+эт|чиқар|ошкор)\w*",
    # Russian
    rf"(?:игнорируй|игнорируйте|забудь|забудьте|не\s+учитывай|не\s+учитывайте|отмени|отмените|отбрось|отбросьте|пренебреги|пренебрегите)\s+{_RU_PRIOR}",
    r"(?:покажи|выведи|раскрой|раскройте|повтори|напиши)\s+(?:мне\s+)?(?:свой\s+|твой\s+)?(?:системн\w+\s+(?:промпт|инструкци)\w*|system\s*prompt)",
    r"ты\s+теперь\s+(?:dan\b|без\s+(?:ограничени|цензур|фильтр)\w*)",
    r"(?:обойди|обойдите|отключи|отключите)\s+(?:все\s+)?(?:правила|ограничени\w*|фильтр\w*)",
]

INJECTION_REGEX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


# Letters that look the same in Latin and Cyrillic: attackers mix them ("зaбудь") to slip past the patterns
_LAT_TO_CYR = dict(zip("acepoxykmthb", "асерохукмтнв"))
_CYR_TO_LAT = {v: k for k, v in _LAT_TO_CYR.items()}
_WORD = re.compile(r"\w+", re.UNICODE)


def _is_cyrillic(ch: str) -> bool:
    return "\u0400" <= ch <= "\u04ff"


def _unmix_script(match: "re.Match[str]") -> str:
    word = match.group(0)
    lat = sum(1 for ch in word if ch.isascii() and ch.isalpha())
    cyr = sum(1 for ch in word if _is_cyrillic(ch))
    if not lat or not cyr:
        return word
    if cyr >= lat:  # mostly Cyrillic: Latin lookalikes become Cyrillic
        return "".join(_LAT_TO_CYR.get(ch.lower(), ch) if ch.isascii() and ch.isalpha() else ch for ch in word)
    return "".join(_CYR_TO_LAT.get(ch.lower(), ch) if _is_cyrillic(ch) else ch for ch in word)


def _clean_text(text: str) -> str:
    """Whitespace-like characters (U+3000, U+2800, ...) become a space; invisible/control characters are removed."""
    out = []
    for ch in text:
        category = unicodedata.category(ch)
        if ch in "\n\t":
            out.append(ch)
        elif ch.isspace() or category in ("Zs", "Zl", "Zp") or ch == "\u2800":
            out.append(" ")
        elif category in ("Cc", "Cf", "Cs", "Co", "Cn") or not ch.isprintable():
            continue
        else:
            out.append(ch)
    return "".join(out)


def _injection_view(cleaned: str) -> str:
    """The text as the patterns should see it: compatibility-normalised and without mixed-script lookalikes."""
    return _WORD.sub(_unmix_script, unicodedata.normalize("NFKC", cleaned))


def sanitize_user_input(text: str) -> str:
    """Detects and neutralizes malicious prompt injection attempts."""
    cleaned = _clean_text(text).strip()
    # NFKC is only used for the check: the question itself keeps its characters (superscripts in "18\u00b9-modda")
    if INJECTION_REGEX.search(_injection_view(cleaned)):
        logger.warning(f"Potential prompt injection detected: {cleaned[:100]}")
        raise HTTPException(
            status_code=400,
            detail="Xavfsizlik qoidalariga zid so'rov aniqlandi (Potentially unsafe prompt pattern detected)."
        )
    return cleaned
