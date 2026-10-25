import asyncio
import json
import logging
import re
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel

from src.config import settings
from src.schema.canonical import CanonicalArticle
from src.retrieval.reranker import RetrievedArticleContext
from src.generation.validator import CitationValidator
from src.clients.openrouter import OpenRouterClient
from src.retrieval.passages import focused_text

logger = logging.getLogger(__name__)

SUPPORT_TEXT_CHARS = 6000      # characters of each cited unit shown to the checker (generation sees up to 7000)

BULLET_PATTERN = re.compile(r"^\s*([-*•])\s+(.*)$")
STEP_PATTERN = re.compile(r"^\s*(\d{1,2})\.\s+(.*)$")   # 1-2 digits: a year ("2024. yilda") is not a step
STEP_HEADER_PATTERN = re.compile(
    r"(nima qilish kerak|harakatlar ketma-ketligi|amalga oshirish tartibi|qadamlar|порядок действий|что делать|next steps|how to apply)",
    re.IGNORECASE,
)

SUPPORT_CHECK_SYSTEM_PROMPT = """Siz O'zbekiston nogironlik huquqlari bo'yicha yuridik fakt-chekersiz (citation support check).
Sizning vazifangiz: berilgan javobdagi har bir da'vo (claim) o'zi iqtibos qilgan qonuniy band(lar) matni bilan tasdiqlanishini QAT'IY tekshirish.

Har bir da'vo uchun quyidagi 3 ta bahodan (verdict) birini bering:
1. "supported" — da'vo keltirilgan band matniga to'liq va aniq mos keladi.
2. "partial" — da'voning asosiy yo'nalishi to'g'ri, lekin uncha muhim bo'lmagan mayda tafsilot to'liq keltirilmagan (lekin qonuniy mohiyat buzilmagan).
3. "unsupported" — quyidagi har qanday holatda QAT'IY ravishda "unsupported" deb belgilang:
   - Band boshqa guruhga tegishli (masalan, band faqat 18 yoshgacha bo'lgan bolalarga tegishli, lekin da'vo katta yoshdagi shaxslarga yordam turi sifatida keltirilgan; yoki faqat harbiylarga oid norma fuqarolarga tatbiq qilingan);
   - Band faqat toifa yoki holatni (masalan kasalliklar ro'yxatini) sanab o'tadi, lekin da'vodagi imtiyoz, to'lov yoki yordam turini aytmaydi;
   - Da'vo band matnida yo'q bo'lgan fakt, davlat organi (masalan bandda yo'q bo'lsa ham "Inson markazi", "mahalla"), muddat yoki talabni qo'shadi;
   - Iqtibos qilingan band manbalar ichida topilmagan yoki da'voga umuman aloqasi yo'q.

JAVOB FORMATI:
Faqat va faqat quyidagi JSON massiv (array) formatida qaytaring:
[
  {"i": 0, "verdict": "supported", "reason": "qisqa sabab"},
  {"i": 1, "verdict": "unsupported", "reason": "band boshqa guruhga (bolalarga) tegishli"}
]
Hech qanday qo'shimcha tushuntirish yoki matn yozmang."""


class Claim(BaseModel):
    index: int
    text: str
    cited_ids: List[str]
    line_no: int
    kind: str  # lead | bullet | step | sentence


class Verdict(BaseModel):
    index: int
    verdict: str  # supported | partial | unsupported
    reason: str = ""


def split_claims(raw_answer: str) -> List[Claim]:
    """
    Xom javobni qatorlar va gaplarga ajratib, ichida [canonical_id] bo'lgan har bir da'voni ajratadi.
    Kind turlari:
      - lead: javobning birinchi mazmunli paragrafi/kirish qismidagi da'vo
      - bullet: "-", "*", "•" bilan boshlangan band
      - step: "1.", "2." kabi raqamli qadam
      - sentence: keyingi paragraflardagi oddiy gap
    """
    claims: List[Claim] = []
    if not raw_answer or not raw_answer.strip():
        return claims

    lines = raw_answer.split("\n")
    first_substantive_seen = False

    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # 1. Bullet tekshiruvi
        m_bullet = BULLET_PATTERN.match(line)
        if m_bullet:
            first_substantive_seen = True
            cids = CitationValidator.extract_canonical_ids(line)
            if cids:
                claims.append(
                    Claim(
                        index=len(claims),
                        text=stripped,
                        cited_ids=cids,
                        line_no=line_idx,
                        kind="bullet",
                    )
                )
            continue

        # 2. Step tekshiruvi
        m_step = STEP_PATTERN.match(line)
        if m_step:
            first_substantive_seen = True
            cids = CitationValidator.extract_canonical_ids(line)
            if cids:
                claims.append(
                    Claim(
                        index=len(claims),
                        text=stripped,
                        cited_ids=cids,
                        line_no=line_idx,
                        kind="step",
                    )
                )
            continue

        # 3. Sarlavhalar (#, **...:**, ...)
        if stripped.startswith("#") or (
            stripped.startswith("**") and (stripped.endswith("**:") or stripped.endswith("**"))
        ) or (stripped.endswith(":") and len(stripped) < 80):
            cids = CitationValidator.extract_canonical_ids(line)
            if not cids:
                continue

        # 4. Oddiy matn (lead yoki sentence)
        cids = CitationValidator.extract_canonical_ids(line)
        if not cids:
            first_substantive_seen = True
            continue

        is_lead = not first_substantive_seen
        first_substantive_seen = True

        # Gaplarga bo'lish
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", stripped) if s.strip()]
        line_claims_added = False
        for sent in sentences:
            sent_cids = CitationValidator.extract_canonical_ids(sent)
            if sent_cids:
                claims.append(
                    Claim(
                        index=len(claims),
                        text=sent,
                        cited_ids=sent_cids,
                        line_no=line_idx,
                        kind="lead" if is_lead else "sentence",
                    )
                )
                line_claims_added = True

        if not line_claims_added:
            claims.append(
                Claim(
                    index=len(claims),
                    text=stripped,
                    cited_ids=cids,
                    line_no=line_idx,
                    kind="lead" if is_lead else "sentence",
                )
            )

    return claims


async def check_support(
    question: str,
    claims: List[Claim],
    contexts: List[RetrievedArticleContext],
    client: OpenRouterClient,
    model: Optional[str] = None,
    timeout: float = 15.0,
) -> List[Verdict]:
    """
    BITTA LLM chaqiruvi orqali har bir da'voning o'zi iqtibos qilgan bandlar bilan tasdiqlanishini baholaydi.
    Har bir da'vo uchun FAQAT u iqtibos qilgan bandlar matni uzatiladi.
    """
    if not claims:
        return []

    ctx_map: Dict[str, CanonicalArticle] = {}
    focus_map: Dict[str, Optional[Dict[str, int]]] = {}
    for c in contexts:
        art = getattr(c, "article", None)
        if art and getattr(art, "canonical_id", None):
            ctx_map[art.canonical_id] = art
            focus_map[art.canonical_id] = getattr(c, "focus", None)

    claims_blocks: List[str] = []
    for c in claims:
        norms_info = []
        for cid in c.cited_ids:
            art = ctx_map.get(cid)
            if art:
                meta = getattr(art, "metadata", None)
                law_num = getattr(meta, "law_number", "noma'lum") if meta else "noma'lum"
                art_num = getattr(meta, "article_number", "noma'lum") if meta else "noma'lum"
                annex_title = getattr(meta, "annex_title", None) if meta else None
                chapter_num = getattr(meta, "chapter_number", None) if meta else None

                text_body = ""
                if hasattr(art, "get_text"):
                    # the part of a long unit the answer was written from (beginning + matched chunk), not its first characters
                    text_body = focused_text(art, "uz", focus_map.get(cid), SUPPORT_TEXT_CHARS)

                info = [
                    f"  - Canonical ID: [{cid}]",
                    f"    Akt raqami: {law_num}",
                    f"    Band raqami: {art_num}",
                ]
                if annex_title:
                    info.append(f"    Ilova/Ro'yxat sarlavhasi: {annex_title}")
                if chapter_num:
                    info.append(f"    Bob: {chapter_num}")
                info.append(f"    Matn: {text_body}")
                norms_info.append("\n".join(info))
            else:
                norms_info.append(f"  - Canonical ID: [{cid}] (Diqqat: Ushbu band qidiruv manbalari orasida TOPILMADI)")

        claims_blocks.append(
            f"DA'VO #{c.index} (turi: {c.kind}):\n"
            f"Da'vo matni: \"{c.text}\"\n"
            f"U iqtibos qilgan bandlar:\n" + ("\n".join(norms_info) if norms_info else "  (Iqtibos yo'q)")
        )

    formatted_claims = "\n\n".join(claims_blocks)
    # a checker that does not reason at length: the chat model unless SUPPORT_CHECK_MODEL names another one
    target_model = model or settings.SUPPORT_CHECK_MODEL or None

    messages = [
        {"role": "system", "content": SUPPORT_CHECK_SYSTEM_PROMPT},
        {"role": "user", "content": f"SAVOL: {question}\n\nDA'VOLAR:\n{formatted_claims}"},
    ]

    try:
        response_text = await asyncio.wait_for(
            client.chat_completion(
                messages=messages,
                model=target_model,
                temperature=0.0,
                max_tokens=2048,
                reasoning={"enabled": False},
                light=True,
            ),
            timeout=timeout,
        )
    except Exception as e:
        logger.warning(f"support_check: LLM error or timeout ({timeout}s): {e}")
        raise e

    response_text = (response_text or "").strip()
    match = re.search(r"\[\s*\{.*\}\s*\]", response_text, re.DOTALL)
    if not match:
        raise ValueError(f"support_check: LLM did not return a valid JSON array: {response_text[:200]}")

    try:
        items = json.loads(match.group(0))
    except Exception as e:
        raise ValueError(f"support_check: JSON parse error: {e}")

    verdicts: List[Verdict] = []
    for item in items:
        try:
            idx = int(item["i"])
            v_str = str(item.get("verdict", "")).strip().lower()
            reason = str(item.get("reason", "")).strip()
            if v_str in ("supported", "partial", "unsupported"):
                verdicts.append(Verdict(index=idx, verdict=v_str, reason=reason))
        except (KeyError, ValueError, TypeError):
            continue

    return verdicts


def apply_verdicts(
    raw_answer: str,
    claims: List[Claim],
    verdicts: List[Verdict],
) -> Tuple[str, int]:
    """
    Verdictlarni xom javobga tatbiq qiladi:
      - "unsupported" bullet va step qatorlarini butunlay olib tashlaydi;
      - Qolgan raqamli qadamlarni qayta raqamlaydi;
      - Qadamsiz qolgan "Nima qilish kerak" (va o'xshash) sarlavhasini olib tashlaydi;
      - Oddiy gapda faqat noto'g'ri iqtibos belgisini olib tashlaydi;
      - "partial" ga tegmaydi.
    Qaytaradi: (yangilangan_matn, tashlangan_da'volar_soni).
    """
    if not claims or not verdicts:
        return raw_answer, 0

    verdict_map = {v.index: v for v in verdicts}
    unsupported_claims = [
        c for c in claims
        if verdict_map.get(c.index) and verdict_map[c.index].verdict == "unsupported"
    ]
    if not unsupported_claims:
        return raw_answer, 0

    unsupported_lines = {
        c.line_no for c in unsupported_claims if c.kind in ("bullet", "step")
    }
    unsupported_sentences = [
        c for c in unsupported_claims if c.kind in ("sentence", "lead")
    ]

    lines = raw_answer.split("\n")
    filtered_lines: List[str] = []

    for line_idx, line in enumerate(lines):
        if line_idx in unsupported_lines:
            # Bullet yoki step butunlay olib tashlanadi
            continue

        modified_line = line
        # Oddiy gap yoki lead dagi noto'g'ri iqtibos belgilarini tozalash
        for c in unsupported_sentences:
            if c.line_no == line_idx:
                for cid in c.cited_ids:
                    # 1. [cid]
                    modified_line = re.sub(rf"\[\s*{re.escape(cid)}\s*\]", "", modified_line)
                    # 2. [cid, ...] yoki [..., cid]
                    modified_line = re.sub(rf"\[\s*{re.escape(cid)}\s*,\s*", "[", modified_line)
                    modified_line = re.sub(rf",\s*{re.escape(cid)}\s*\]", "]", modified_line)
                    # 3. Yolg'iz cid
                    modified_line = re.sub(rf"\b{re.escape(cid)}\b", "", modified_line)

        modified_line = re.sub(r"\[\s*\]", "", modified_line)
        modified_line = re.sub(r"\s+([.,;:!?])", r"\1", modified_line)
        modified_line = re.sub(r"[ \t]{2,}", " ", modified_line)
        filtered_lines.append(modified_line)

    # 1. Qadamlarni qayta raqamlash (renumbering)
    renumbered_lines: List[str] = []
    step_counter = 0
    for line in filtered_lines:
        m = STEP_PATTERN.match(line)
        if m:
            step_counter += 1
            indent = line[:line.find(m.group(1))]
            content = m.group(2)
            renumbered_lines.append(f"{indent}{step_counter}. {content}")
        else:
            stripped = line.strip()
            if stripped and not BULLET_PATTERN.match(line):
                step_counter = 0
            renumbered_lines.append(line)

    # 2. Qadamsiz qolgan "Nima qilish kerak" sarlavhasini olib tashlash
    final_lines: List[str] = []
    i = 0
    while i < len(renumbered_lines):
        line = renumbered_lines[i]
        stripped = line.strip()
        if STEP_HEADER_PATTERN.search(stripped) and not STEP_PATTERN.match(line):
            # Keyingi bo'lim sarlavhasigacha step bormi tekshirish
            has_steps = False
            j = i + 1
            while j < len(renumbered_lines):
                nxt = renumbered_lines[j].strip()
                if nxt.startswith(("#", "---")) or (
                    nxt.startswith("**") and nxt.endswith("**") and not STEP_PATTERN.match(nxt)
                ):
                    break
                if STEP_PATTERN.match(nxt):
                    has_steps = True
                    break
                j += 1
            if not has_steps:
                i += 1
                while i < len(renumbered_lines) and not renumbered_lines[i].strip():
                    i += 1
                continue

        final_lines.append(line)
        i += 1

    res_text = "\n".join(final_lines)
    res_text = re.sub(r"\n{3,}", "\n\n", res_text).strip()

    # only bullets and steps are removed; for plain sentences just the citation mark disappears
    dropped = sum(1 for c in unsupported_claims if c.kind in ("bullet", "step"))
    return res_text, dropped


async def run_support_check(
    raw_answer: str,
    question: str,
    contexts: List[RetrievedArticleContext],
    client: OpenRouterClient,
    original_messages: Optional[List[Dict[str, str]]] = None,
    language: str = "uz",
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    reasoning: Optional[Dict] = None,
) -> Tuple[str, List[str]]:
    """
    Umumiy citation support check pipeline:
      1. Claims ajratish
      2. Check support (LLM)
      3. Agar lead yoki da'volarning yarmidan ko'pi unsupported bo'lsa -> BIR marta qayta generatsiya va qayta tekshiruv
      4. Apply verdicts
      5. Fail-open (xato/timeout bo'lsa -> javob o'zgarmaydi, warning "support_check_skipped")
    """
    if not settings.SUPPORT_CHECK_ENABLED:
        return raw_answer, []

    # Rad javoblarida tekshiruv ishlamaydi
    retrieved_ids = {ctx.article.canonical_id for ctx in contexts if getattr(ctx, "article", None)}
    if CitationValidator._detect_refusal(raw_answer, retrieved_ids):
        return raw_answer, []

    claims = split_claims(raw_answer)
    if not claims:
        return raw_answer, []

    timeout_s = timeout if timeout is not None else settings.SUPPORT_CHECK_TIMEOUT_S

    try:
        verdicts = await check_support(
            question=question,
            claims=claims,
            contexts=contexts,
            client=client,
            model=model,
            timeout=timeout_s,
        )
    except Exception as e:
        logger.warning(f"support_check skipped due to error: {e}")
        return raw_answer, ["support_check_skipped"]

    verdict_map = {v.index: v for v in verdicts}
    unsupported_claims = [
        c for c in claims
        if verdict_map.get(c.index) and verdict_map[c.index].verdict == "unsupported"
    ]

    lead_unsupported = any(
        c.kind == "lead" and verdict_map.get(c.index) and verdict_map[c.index].verdict == "unsupported"
        for c in claims
    )
    majority_unsupported = len(unsupported_claims) > (len(claims) / 2)

    # Agar lead yoki da'volarning yarmidan ko'pi unsupported bo'lsa -> BIR marta qayta generatsiya
    if (lead_unsupported or majority_unsupported) and original_messages:
        bad_texts = [f"- {c.text}" for c in unsupported_claims]
        missing_summary = "\n".join(bad_texts)
        regen_instruction = (
            f"Quyidagi da'volar manbada yo'q:\n{missing_summary}\n"
            f"Ularsiz qayta yozing."
        )
        regen_messages = list(original_messages) + [
            {"role": "assistant", "content": raw_answer},
            {"role": "user", "content": regen_instruction},
        ]
        try:
            regen_model = model or getattr(client, "primary_model", None) or settings.GENERATION_MODEL_PRIMARY
            regen_response = await asyncio.wait_for(
                client.chat_completion(
                    messages=regen_messages,
                    model=regen_model,
                    temperature=0.0,
                    max_tokens=8192,
                    reasoning=reasoning,
                ),
                timeout=timeout_s * 2,
            )
            regen_response = (regen_response or "").strip()
            if regen_response and len(regen_response) >= 50:
                new_claims = split_claims(regen_response)
                if new_claims:
                    try:
                        new_verdicts = await check_support(
                            question=question,
                            claims=new_claims,
                            contexts=contexts,
                            client=client,
                            model=model,
                            timeout=timeout_s,
                        )
                        final_text, dropped = apply_verdicts(regen_response, new_claims, new_verdicts)
                        warnings = [f"support_check: regenerated; dropped {dropped}/{len(new_claims)} claims"]
                        return final_text, warnings
                    except Exception as e:
                        logger.warning(f"support_check: second check failed: {e}")
                        return regen_response, ["support_check_skipped"]
                return regen_response, ["support_check: regenerated"]
        except Exception as e:
            logger.warning(f"support_check: regeneration failed: {e}")
            # Fallback to apply_verdicts on original answer

    final_text, dropped = apply_verdicts(raw_answer, claims, verdicts)
    warnings = []
    if dropped > 0:
        warnings.append(f"support_check: dropped {dropped}/{len(claims)} claims")
    return final_text, warnings
