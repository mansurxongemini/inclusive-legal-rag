from typing import List, Literal
from src.retrieval.reranker import RetrievedArticleContext

ResponseMode = Literal["plain", "legal_text", "subsumption"]

DISCLAIMERS = {
    "uz": (
        "\n\n---\n*Eslatma: Ushbu ma'lumot O'zbekiston Respublikasining amaldagi qonunchiligi asosida axborot va tushuntirish berish maqsadida taqdim etildi. "
        "U vakolatli davlat organlarining rasmiy qarori yoki sud hujjati o'rnini bosmaydi.*"
    ),
    "ru": (
        "\n\n---\n*Примечание: Данная информация носит информационно-разъяснительный характер на основе действующего законодательства Республики Узбекистан "
        "и не заменяет официальное решение уполномоченных государственных органов или судебный акт.*"
    ),
    "en": (
        "\n\n---\n*Disclaimer: This information is provided for informational purposes based on current legislation of the Republic of Uzbekistan and "
        "does not substitute for official decisions by competent state bodies or court rulings.*"
    ),
}

REFUSAL_MESSAGES = {
    "uz": (
        "Taqdim etilgan O'zbekiston Respublikasi qonunchilik hujjatlarida ushbu masala bo'yicha aniq norma topilmadi. "
        "Noto'g'ri ma'lumot berilishining oldini olish maqsadida, masalaga oydinlik kiritish uchun vakolatli davlat organlariga yoki "
        "Adliya vazirligining 'Madad' nodavlat notijorat tashkilotiga (www.advice.uz) murojaat qilishni tavsiya etamiz."
    ),
    "ru": (
        "В предоставленных законодательных актах Республики Узбекистан не найдено прямой нормы по данному вопросу. "
        "В целях предоставления точной информации рекомендуем обратиться в уполномоченные государственные органы или "
        "правовую организацию «Мадад» при Министерстве юстиции (www.advice.uz)."
    ),
    "en": (
        "No explicit legal provision governing this specific question was found in the retrieved legislation of the Republic of Uzbekistan. "
        "To ensure accuracy, we recommend consulting the relevant state authority or the Ministry of Justice's legal assistance portal (www.advice.uz)."
    ),
}


def build_system_prompt(language: str = "uz", mode: ResponseMode = "plain") -> str:
    lang_instruction = {
        "uz": "Javobni sof o'zbek tilida (lotin yozuvida), ravon, tushunarli va professional tilda yozing.",
        "ru": "Отвечайте грамотно, доступно и профессионально на русском языке.",
        "en": "Answer clearly, professionally, and accessibly in English.",
    }.get(language, "Javobni o'zbek tilida yozing.")

    if mode == "subsumption":
        mode_instruction = (
            "CHUQUR HUQUQIY TAHLIL VA SUBSUMSIYA REJIMI:\n"
            "Javobni quyidagi 4 bosqichli amaliy yuridik struktura asosida tuzing (hech qanday nemischa so'zlarni ishlatmang):\n"
            "1. 🏛️ HUQUQIY ASOS: Masalaga bevosita taalluqli qonun yoki kodeks moddalari.\n"
            "2. 📋 QO'LLANILISH SHARTLARI: Normada belgilangan shartlar va subyektlar doirasi (kimlarga, qanday asosda tatbiq etilishi).\n"
            "3. ⚠️ MUHIM ISTISNOLAR VA CHEKLOVLAR: Qonunda ko'rsatilgan istisno holatlar yoki maxsus talablar.\n"
            "4. ⚖️ AMALIY XULOSA VA HUQUQIY OQIBAT: Fuqaroning aniq huquqlari, imtiyozlari va vakolatli organga murojaat qilish tartibi."
        )
    elif mode == "legal_text":
        mode_instruction = (
            "YURIDIK RASMIY MATN REJIMI: Moddalarning rasmiy qonuniy matnini va formulirovkasini aniq keltiring, "
            "rasmiy organlarga taqdim etish uchun tegishli moddalar va bandlarni to'liq iqtibos qilib bering."
        )
    else:
        mode_instruction = (
            "SODDA VA TUSHUNARLI TIL REJIMI (Professional Yuridik Maslahat):\n"
            "Xuddi tajribali professional yurist yoki advokat fuqaroga yuzma-yuz maslahat bergandek samimiy, aniq, tushunarli va amaliy foydali tahlil bering. "
            "Quruq moddalar ro'yxatini chiqarib qo'ymang! Imtiyozlarni mantiqiy sohalarga ajrating (masalan: Tibbiyot, Mehnat, Transport, Ta'lim, Ijtimoiy yordam). "
            "Har bir sohada fuqaro aniq nimalarga ega bo'lishini va qanday shartlar borligini ixcham, ravon va tushunarli qilib yoritib bering."
        )

    prompt = f"""You are the official Uzbekistan Legal AI Advisor, providing accurate, human-like, and highly practical legal guidance grounded exclusively in the retrieved legal context.

{lang_instruction}

CORE PROFESSIONAL GUIDELINES:
1. ACT AS AN EXPERT HUMAN LAWYER / ADVISOR: Synthesize legal provisions into clear, well-structured, actionable advice. Do NOT dump dry lists of articles. Explain what rights, benefits, procedures, or protections exist in plain, professional language.
2. CITATION DISCIPLINE: Every specific factual or legal right, duty, or benefit MUST be anchored with its canonical ID in brackets at the end of the sentence or bullet (e.g. [law_disability_2020_art_15]).
   - Do NOT invent or cite canonical IDs that are not provided in the CONTEXT below.
   - Do NOT clutter the sentence with redundant law titles repeatedly; a concise explanation followed by [canonical_id] is best.
3. AMALIY YO'NALTIRISH (PRACTICAL ACTIONABILITY): Fuqaroda hech qanday noaniqlik qolmasligi uchun, imkon qadar quyidagi 4 ta muhim jihatni yoritib bering:
   - ⚖️ **Nima va Nega (Huquqiy asos):** Fuqaroning huquqi yoki majburiyatining qonuniy asosi.
   - 🏛️ **Kim vakolatdor va Qayerga borish kerak:** Mas'ul davlat organi yoki tashkilot (masalan: Pensiya jamg'armasi, "Inson" ijtimoiy markazi, Davlat xizmatlari markazi, my.gov.uz portali va h.k.).
   - 📝 **Qanday qilaman (Amaliy harakatlar):** Ariza berish, qanday hujjatlar taqdim etish va tartibi.
   - ⏱️ **Muddatlar va talablar:** Ariza ko'rib chiqish muddatlari, imtiyoz shartlari yoki to'lov tartibi.
4. STRUCTURE & BREVITY: Use clean markdown headers and bullet points. Be concise and high-density to save token budget without sacrificing clarity.
5. HONESTY: If the retrieved articles DO NOT answer the question, state so politely and clearly. Never fabricate provisions or hallucinate non-existent benefits.
6. STATUS AWARENESS: If any cited article is marked as AMENDED or REPEALED in the context, explicitly inform the user that it is no longer current and cite the active replacement.
7. Mode Instructions: {mode_instruction}
8. MULTI-ISSUE THOROUGHNESS: If the user asks about multiple aspects (e.g. who has priority to stay at work, special guarantees for pregnant women, persons with disabilities, notification periods, compensation), systematically answer EACH sub-issue in its own clear section using the relevant cited statute.
9. Mode Instructions: {mode_instruction}
10. Always conclude your response with the mandatory legal disclaimer.
NON-NEGOTIABLE GROUNDING AND ANTI-HALLUCINATION RULES:
Only state claims that are 100% supported by the retrieved context.
"""
    return prompt.strip()


def format_context_for_llm(contexts: List[RetrievedArticleContext], language: str = "uz") -> str:
    if not contexts:
        return "NO RELEVANT ARTICLES RETRIEVED."

    context_blocks = []
    for ctx in contexts:
        art = ctx.article
        title = art.get_title(language)
        law_title = art.get_law_title(language)
        body = art.get_text(language)
        status_line = f"Status: {art.metadata.status.value.upper()}"
        if ctx.is_superseded and ctx.superseded_by:
            status_line += f" (BEKOR QILINGAN / AMENDED - Yangi tahrir: {ctx.superseded_by})"

        points_text = ""
        if art.points:
            pt_lines = [f"  - {pt.point_id}-band: {pt.text.get(language, pt.text.get('uz', ''))}" for pt in art.points]
            points_text = "\nPoints/Bandlar:\n" + "\n".join(pt_lines)

        block = f"""---
Canonical ID: [{art.canonical_id}]
Law: {law_title} (Qonun raqami: {art.metadata.law_number})
Article: {art.metadata.article_number} — {title}
{status_line}
Official URL: {art.metadata.source_url}
Text:
{body}{points_text}
---"""
        context_blocks.append(block)

    return "\n\n".join(context_blocks)
