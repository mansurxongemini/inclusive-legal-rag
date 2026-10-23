"""
Sources-only answer for the case that no generation model is reachable: instead of an error page the user gets the
text of the norms that match the question, quoted from the legal database and cited like any other answer. No model
writes a word of it, so nothing in it can be invented.
"""
from typing import List, Sequence

from src.retrieval.passages import focused_text

INTRO = {
    "uz": ("Javob yaratish xizmati hozir ishlamayapti, shuning uchun savolingizga eng yaqin normalarning matnini "
           "keltiraman. Bu tayyor javob emas: ma'noni aniqlashtirish uchun vakolatli organga murojaat qiling yoki "
           "birozdan so'ng qayta urinib ko'ring."),
    "ru": ("Сервис формирования ответов сейчас недоступен, поэтому привожу тексты норм, наиболее близких к вашему "
           "вопросу. Это не готовый ответ: за разъяснением обратитесь в уполномоченный орган или повторите запрос позже."),
    "en": ("The answer service is unavailable right now, so here is the text of the provisions closest to your question. "
           "This is not a finished answer: ask the competent authority for clarification or try again shortly."),
}
INTRO_UZ_CYRL = ("Жавоб яратиш хизмати ҳозир ишламаяпти, шунинг учун саволингизга энг яқин нормалар матнини келтираман. "
                 "Бу тайёр жавоб эмас: маънони аниқлаштириш учун ваколатли органга мурожаат қилинг ёки бироздан сўнг "
                 "қайта уриниб кўринг.")
EXCERPT_CHARS = 450


def sources_only_text(contexts: Sequence, language: str, limit: int = 3, query: str = "") -> str:
    """Intro plus up to `limit` quoted units, each ending with its [canonical_id] (the validator turns it into [n])."""
    statutory = [c for c in contexts if not c.article.canonical_id.startswith(("qa_", "hp_"))]
    chosen: List = (statutory or list(contexts))[:limit]
    from src.generation.prompts import is_uz_cyrillic      # prompts imports the retrieval layer: keep this import lazy
    lines = [INTRO_UZ_CYRL if is_uz_cyrillic(language, query) else INTRO.get(language, INTRO["uz"]), ""]
    for ctx in chosen:
        art = ctx.article
        meta = art.metadata
        excerpt = focused_text(art, language, getattr(ctx, "focus", None), EXCERPT_CHARS).strip()
        lines.append(f"- {art.get_law_title(language)} ({meta.law_number}), {meta.article_number}: «{excerpt}» "
                     f"[{art.canonical_id}]")
    return "\n".join(lines)
