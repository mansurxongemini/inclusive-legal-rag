import re
import logging
from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)

# Prompt injection patterns. Non-English ones only match imperative forms ("forget the previous rules"), so
# ordinary legal questions such as "avvalgi qoidalar bekor qilinganmi?" are not blocked.
_APOS = "['\u02bb\u02bc\u2018\u2019`\u00b4]?"
_UZ_LAT_PRIOR = r"(?:oldingi|avvalgi|yuqoridagi|barcha)\s+(?:barcha\s+)?(?:ko{a}rsatma|yo{a}riqnoma|qoida|buyruq|prompt)\w*".format(a=_APOS)
_UZ_LAT_IGNORE = r"(?:unut(?:ing|ingiz|inglar|gin)?|e{a}tibor(?:ga)?\s+(?:berma|olma)(?:ng|ngiz|nglar|gin)|e{a}tiborsiz\s+qoldir(?:ing|ingiz|inglar|gin)?)\b".format(a=_APOS)
_UZ_CYR_PRIOR = r"(?:олдинги|аввалги|юқоридаги|барча)\s+(?:барча\s+)?(?:кўрсатма|йўриқнома|қоида|буйруқ|промпт)\w*"
_UZ_CYR_IGNORE = r"(?:унут(?:инг|ингиз|инглар|гин)?|эътибор(?:га)?\s+(?:берма|олма)(?:нг|нгиз|нглар|гин)|эътиборсиз\s+қолдир(?:инг|ингиз|инглар|гин)?)\b"
_RU_PRIOR = r"(?:все\s+|любые\s+|всю\s+)?(?:предыдущ|прежн|прошл|вышестоящ)\w*\s+(?:инструкци|указани|правил|команд|промпт)\w*"

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"forget\s+(all\s+)?(previous|prior)\s+instructions",
    r"system\s*prompt\s*override",
    r"you\s+are\s+now\s+dan",
    r"bypass\s+rules",
    r"jailbreak",
    r"you\s+must\s+act\s+as\s+unfiltered",
    # Uzbek (Latin): "oldingi ko'rsatmalarni unuting", "barcha qoidalarga e'tibor bermang", "system promptni ko'rsat"
    rf"{_UZ_LAT_PRIOR}\s+{_UZ_LAT_IGNORE}",
    rf"{_UZ_LAT_IGNORE}\s+{_UZ_LAT_PRIOR}",
    rf"(?:system\s*prompt|tizim\s+prompt|tizim\s+ko{_APOS}rsatma)\w*\s+(?:ni\s+)?(?:ko{_APOS}rsat|ayt|chop\s+et|chiqar|oshkor)\w*",
    rf"(?:cheklovsiz|cheklovlarsiz|filtrsiz)\s+(?:rejim|rol)\w*",
    # Uzbek (Cyrillic)
    rf"{_UZ_CYR_PRIOR}\s+{_UZ_CYR_IGNORE}",
    rf"{_UZ_CYR_IGNORE}\s+{_UZ_CYR_PRIOR}",
    r"(?:system\s*prompt|тизим\s+промпт)\w*\s+(?:ни\s+)?(?:кўрсат|айт|чоп\s+эт|чиқар|ошкор)\w*",
    # Russian
    rf"(?:игнорируй|игнорируйте|забудь|забудьте|не\s+учитывай|не\s+учитывайте|отмени|отмените)\s+{_RU_PRIOR}",
    r"(?:покажи|выведи|раскрой|раскройте|повтори|напиши)\s+(?:мне\s+)?(?:свой\s+|твой\s+)?(?:системн\w+\s+(?:промпт|инструкци)\w*|system\s*prompt)",
    r"ты\s+теперь\s+(?:dan\b|без\s+(?:ограничени|цензур|фильтр)\w*)",
    r"(?:обойди|обойдите|отключи|отключите)\s+(?:все\s+)?(?:правила|ограничени\w*|фильтр\w*)",
]

INJECTION_REGEX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


def sanitize_user_input(text: str) -> str:
    """Detects and neutralizes malicious prompt injection attempts."""
    # Strip dangerous non-printable control characters first, so they cannot be used to split a trigger phrase
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t").strip()
    if INJECTION_REGEX.search(cleaned):
        logger.warning(f"Potential prompt injection detected: {cleaned[:100]}")
        raise HTTPException(
            status_code=400,
            detail="Xavfsizlik qoidalariga zid so'rov aniqlandi (Potentially unsafe prompt pattern detected)."
        )
    return cleaned
