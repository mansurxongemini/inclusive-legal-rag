"""
Post-generation guards that need no judge model: the answer is written in the script of the question, contains none
of the wording the prompt forbids, states no amount, deadline or percentage that is absent from the sources and cites
only the units it was given (a model shown point 44 of a regulation may "cite" point 46 by extrapolating the id).
An answer that fails is repaired by ONE regeneration that names the problems; if the repair is not better, the
original is kept and the problems are returned as warnings.
"""
import asyncio
import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple

from src.config import settings
from src.generation.answer_checks import banned_phrases, script_ok, script_share, strip_disclaimer, ungrounded_numbers

logger = logging.getLogger(__name__)

_BRACKET_ID = re.compile(r"\[[A-Za-z0-9_\-]*_[A-Za-z0-9_\-]+(?:\s*[,;]\s*[A-Za-z0-9_\-]*_[A-Za-z0-9_\-]+)*\]")      # [canonical_id] (always has an underscore)

REPAIR_INSTRUCTIONS = {
    "script": {
        "uz": "Javobni savol yozilgan yozuvda (kirill alifbosida) qayta yozing: butun matn o'zbek tilida, kirill yozuvida bo'lsin.",
        "ru": "Перепишите ответ целиком на русском языке.",
        "en": "Rewrite the whole answer in English.",
    },
    "banned": "Javobda \"kontekst\" yoki \"taqdim etilgan hujjatlar\" kabi iboralarni ishlatmang: ular o'rniga to'g'ridan-to'g'ri javob bering.",
    "numbers": "Quyidagi raqamlar manbada yo'q: {numbers}. Ularni olib tashlang yoki manbadagi aniq qiymat bilan almashtiring; manbada yo'q raqam yozmang.",
    "unknown_ids": "Quyidagi manbalar sizga berilmagan: {ids}. Shu manbalarga tayangan gaplarni javobdan olib tashlang; ularni boshqa manbaga ko'chirmang. Faqat berilgan manbalarda yozilgan narsani yozing.",
}


def source_texts(contexts: Sequence, language: str) -> List[str]:
    """Everything an answer may quote numbers from: the unit texts and the act/unit labels shown to the model."""
    texts: List[str] = []
    for ctx in contexts:
        art = getattr(ctx, "article", None)
        if art is None:
            continue
        for lang in {language, "uz", "ru"}:
            try:
                texts.append(art.get_text(lang) or "")
            except Exception:
                pass
        meta = art.metadata
        texts.append(" ; ".join(str(x) for x in (
            meta.law_number, meta.promulgation_date, meta.article_number, meta.chapter_number, meta.annex_title,
            art.get_title(language), art.get_law_title(language)) if x))
    return texts


def unknown_citations(answer: str, contexts: Sequence) -> List[str]:
    """Ids cited in brackets that are not among the units the model was given (the validator would drop them)."""
    from src.generation.validator import CitationValidator
    given = {c.article.canonical_id for c in contexts if getattr(c, "article", None) is not None}
    cited = CitationValidator.extract_canonical_ids(strip_disclaimer(answer))
    return [cid for cid in cited if cid not in given and CitationValidator._ID_LIKE.match(cid)]


def find_issues(question: str, answer: str, contexts: Sequence, language: str) -> Dict:
    body = _BRACKET_ID.sub(" ", strip_disclaimer(answer))
    return {
        "script": not script_ok(question, body, language),
        "banned": banned_phrases(body),
        "numbers": ungrounded_numbers(body, source_texts(contexts, language), question),
        "unknown_ids": unknown_citations(answer, contexts),
    }


def issue_count(issues: Dict) -> int:
    return int(bool(issues["script"])) + len(issues["banned"]) + len(issues["numbers"]) + len(issues["unknown_ids"])


def issue_warnings(issues: Dict) -> List[str]:
    out = []
    if issues["script"]:
        out.append("script_mismatch: the answer is not written in the script of the question")
    if issues["banned"]:
        out.append("forbidden_wording: " + ", ".join(issues["banned"]))
    if issues["numbers"]:
        out.append("ungrounded_numbers: " + ", ".join(issues["numbers"]))
    if issues["unknown_ids"]:
        out.append("unknown_citations: " + ", ".join(issues["unknown_ids"]))
    return out


def repair_message(issues: Dict, language: str, question: str) -> str:
    parts = []
    if issues["script"]:
        text = REPAIR_INSTRUCTIONS["script"].get(language, REPAIR_INSTRUCTIONS["script"]["uz"])
        if language == "uz" and script_share(question)["cyrillic"] <= script_share(question)["latin"]:
            text = "Javobni savol yozilgan yozuvda (lotin alifbosida) qayta yozing: butun matn o'zbek tilida, lotin yozuvida bo'lsin."
        parts.append(text)
    if issues["banned"]:
        parts.append(REPAIR_INSTRUCTIONS["banned"])
    if issues["numbers"]:
        parts.append(REPAIR_INSTRUCTIONS["numbers"].format(numbers=", ".join(issues["numbers"])))
    if issues["unknown_ids"]:
        parts.append(REPAIR_INSTRUCTIONS["unknown_ids"].format(ids=", ".join(f"[{i}]" for i in issues["unknown_ids"])))
    return " ".join(parts) + " Boshqa hamma narsani (iqtiboslar, tuzilma) o'zgartirmang; faqat tuzatilgan javobni yozing."


async def guard_answer(
    client,
    messages: List[Dict[str, str]],
    raw_answer: str,
    question: str,
    contexts: Sequence,
    language: str,
    reasoning: Optional[Dict] = None,
    max_tokens: int = 8192,
) -> Tuple[str, List[str]]:
    """(answer, warnings): the answer after at most one repair round, and the problems that remain."""
    if not settings.ANSWER_GUARDS_ENABLED or not raw_answer.strip() or getattr(client, "is_mock", False):
        return raw_answer, []
    issues = find_issues(question, raw_answer, contexts, language)
    if not issue_count(issues):
        return raw_answer, []

    try:
        repaired = await asyncio.wait_for(
            client.chat_completion(
                messages=list(messages) + [
                    {"role": "assistant", "content": raw_answer},
                    {"role": "user", "content": repair_message(issues, language, question)},
                ],
                temperature=0.0,
                max_tokens=max_tokens,
                reasoning=reasoning,
            ),
            timeout=settings.ANSWER_REPAIR_TIMEOUT_S,
        )
    except Exception as e:
        logger.warning(f"answer repair failed: {type(e).__name__}: {e}")
        return raw_answer, issue_warnings(issues)

    repaired = (repaired or "").strip()
    if len(repaired) < 50:
        return raw_answer, issue_warnings(issues)
    new_issues = find_issues(question, repaired, contexts, language)
    if issue_count(new_issues) < issue_count(issues):
        logger.info(f"answer repaired: {issue_count(issues)} -> {issue_count(new_issues)} issues")
        return repaired, ["answer_repaired"] + issue_warnings(new_issues)
    return raw_answer, issue_warnings(issues)
