"""
Multi-Aspect Cross-Domain Legal Query Decomposer.
Decomposes compound, multi-issue citizen questions into focused legal sub-queries,
ensuring comprehensive retrieval across all intersecting legal domains without topic crowding.
"""

import re
from typing import List, Tuple
from pydantic import BaseModel
from src.nlp.legal_synonyms import LegalSynonymExpander


class LegalSubQuery(BaseModel):
    query_text: str
    enriched_query: str
    aspect_tag: str = "general"
    domain: str = "general"


class LegalQueryDecomposer:
    """Decomposes compound legal queries into focused sub-queries across legal domains."""

    # Disability-rights domains: (domain_key, regex over the user's words, statutory enrichment terms)
    DOMAIN_TAXONOMY: List[Tuple[str, str, str]] = [
        (
            "tiek",
            r"\b(tmek|tiek|vtek|ekspertiza\w*|ekspert komissiya\w*|nogironlik guruh\w*|nogironlikni belgila\w*|qayta ko['`’‘ʻʼ]?rik\w*|"
            r"nogironlik belgila\w*|медико-социальн\w*|мсэк|втэк|признани\w* инвалид\w*|групп\w* инвалидности)\b",
            "tibbiy-ijtimoiy ekspert komissiyasi nogironlikni belgilash tibbiy-ijtimoiy ekspertiza",
        ),
        (
            "pensiya_nafaqa",
            r"\b(pensiya\w*|nafaqa\w*|kompensatsiya\w*|moddiy yordam\w*|ijtimoiy to['`’‘ʻʼ]?lov\w*|reyestr\w*|пенси\w*|пособи\w*|выплат\w*)\b",
            "nogironlik pensiyasi nafaqa tayinlash ijtimoiy to'lovlar moddiy yordam",
        ),
        (
            "mehnat",
            r"\b(mehnat\w*|ish o['`’‘ʻʼ]?rn\w*|ish vaqt\w*|ishga\w*|ish beruvchi\w*|xodim\w*|bandlik\w*|kvota\w*|ishsiz\w*|"
            r"работ\w*|труд\w*|квот\w*|занятост\w*)\b",
            "nogironligi bo'lgan shaxslarni ishga joylashtirish ish o'rinlari kvotasi mehnat shartlari",
        ),
        (
            "reabilitatsiya",
            r"\b(reabilitatsiya\w*|protez\w*|ortopedi\w*|aravacha\w*|eshitish apparat\w*|texnik vosita\w*|sanatoriy\w*|yo['`’‘ʻʼ]?llanma\w*|"
            r"реабилитац\w*|протез\w*|коляск\w*|санатори\w*)\b",
            "reabilitatsiyaning texnik vositalari protez-ortopediya buyumlari reabilitatsiya dasturi",
        ),
        (
            "talim",
            r"\b(ta['`’‘ʻʼ]?lim\w*|maktab\w*|inklyuziv\w*|universitet\w*|oliy ta['`’‘ʻʼ]?lim\w*|grant\w*|talaba\w*|bog['`’‘ʻʼ]?cha\w*|"
            r"образован\w*|школ\w*|инклюзив\w*|вуз)\b",
            "inklyuziv ta'lim alohida ta'lim ehtiyojlari bo'lgan bolalar ta'lim olish huquqi",
        ),
        (
            "qulaylik",
            r"\b(to['`’‘ʻʼ]?siq\w*|pandus\w*|lift\w*|qulay muhit\w*|bino\w*|infratuzilma\w*|axborotdan\w*|imo-ishora\w*|brayl\w*|"
            r"доступн\w*|безбарьерн\w*)\b",
            "to'siqsiz muhit qulay muhit obyektlar va xizmatlarning qulayligi axborotdan foydalanish",
        ),
        (
            "transport",
            r"\b(transport\w*|chipta\w*|yo['`’‘ʻʼ]?l haqi\w*|avtobus\w*|poyezd\w*|metro|taksi|avtomobil\w*|транспорт\w*|проезд\w*)\b",
            "jamoat transportidan imtiyozli foydalanish yo'l haqi chegirma nogironligi bo'lgan shaxslar",
        ),
        (
            "uyjoy_soliq",
            r"\b(uy-joy\w*|kvartira\w*|turar joy\w*|kommunal\w*|ipoteka\w*|soliq\w*|davlat boji\w*|жиль[еёя]\w*|налог\w*)\b",
            "uy-joy bilan ta'minlash kommunal to'lovlar imtiyozlari soliq imtiyozlari ozod etish",
        ),
        (
            "tibbiyot",
            r"\b(tibbiy\w*|dori\w*|davolan\w*|shifoxona\w*|kasalxona\w*|poliklinika\w*|retsept\w*|operatsiya\w*|aperatsiya\w*|jarroh\w*|order\w*|buyrak\w*|"
            r"медицинск\w*|лекарств\w*|лечени\w*|операци\w*|хирург\w*|ордер\w*)\b",
            "ixtisoslashtirilgan tibbiy yordam jarrohlik amaliyoti operatsiya imtiyozli yo'llanma order dori vositalari bepul tibbiy xizmat",
        ),
        (
            "himoya_shikoyat",
            r"\b(shikoyat\w*|sud\w*|kamsit\w*|huquqbuzarlik\w*|javobgarlik\w*|ombudsman\w*|vasiy\w*|homiy\w*|"
            r"жалоб\w*|суд\w*|дискриминац\w*|опек\w*)\b",
            "huquqlarni himoya qilish shikoyat qilish kamsitishga yo'l qo'ymaslik sud himoyasi",
        ),
    ]

    CONJUNCTION_SPLIT_REGEX = re.compile(
        r"\b(?:hamda|shuningdek|shu bilan birga|shu jumladan|bir vaqtda|qolaversa|alohida|birinchi navbatda|ikkinchi navbatda|а также|вместе с тем)\b",
        re.IGNORECASE
    )

    @classmethod
    def extract_numbered_questions(cls, text: str) -> List[str]:
        """Extracts numbered case questions (e.g. '1. Garov va tasarruf ...', '2. Yirik bitim ...')."""
        pattern = r"(?:^|\n)\s*(?:\*\*)?(?:[1-9]|10)[\.\)\-–—:]\s*(?:\*\*)?\s*(?:\[?[1-9]\]?[\:\s]*)?(?:savol|masala|talab)?[:\s]*(.+?)(?=(?:\n\s*(?:\*\*)?(?:[1-9]|10)[\.\)\-–—:]|\Z))"
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        questions = []
        for m in matches:
            q_clean = " ".join(m.strip().split())
            if len(q_clean) > 20:
                questions.append(q_clean[:400])
        return questions

    @classmethod
    def detect_domains(cls, text: str) -> List[Tuple[str, str]]:
        """Identifies all active legal domains and their enrichment strings."""
        detected = []
        for domain_key, pat, enrich in cls.DOMAIN_TAXONOMY:
            if re.search(pat, text, re.IGNORECASE):
                detected.append((domain_key, enrich))
        return detected

    @classmethod
    def decompose(cls, query: str, max_subqueries: int = 4) -> List[LegalSubQuery]:
        cleaned = query.strip()
        if not cleaned:
            return []

        # Check if the query is a structured case study containing multiple numbered questions
        case_questions = cls.extract_numbered_questions(cleaned)
        if len(case_questions) >= 2:
            subqueries: List[LegalSubQuery] = []
            for idx, q_text in enumerate(case_questions[:max_subqueries], 1):
                q_domains = cls.detect_domains(q_text)
                dom_key = q_domains[0][0] if q_domains else "case_question"
                enrichment = " ".join(d[1] for d in q_domains[:2])
                focused = f"{q_text} ({enrichment})" if enrichment else q_text
                enriched = LegalSynonymExpander.build_enriched_search_query(focused)
                subqueries.append(LegalSubQuery(
                    query_text=q_text,
                    enriched_query=enriched,
                    aspect_tag=f"case_q{idx}",
                    domain=dom_key
                ))
            if subqueries:
                return subqueries

        word_count = len(cleaned.split())
        detected_domains = cls.detect_domains(cleaned)

        # Base case: very short query with single domain -> simple return
        if word_count < 8 and len(detected_domains) <= 1:
            enriched = LegalSynonymExpander.build_enriched_search_query(cleaned)
            dom_key = detected_domains[0][0] if detected_domains else "general"
            return [LegalSubQuery(query_text=cleaned, enriched_query=enriched, aspect_tag="primary", domain=dom_key)]

        subqueries: List[LegalSubQuery] = []

        # 1. Full original query as primary
        primary_enriched = LegalSynonymExpander.build_enriched_search_query(cleaned[:600])
        primary_dom = detected_domains[0][0] if detected_domains else "general"
        subqueries.append(LegalSubQuery(
            query_text=cleaned[:600],
            enriched_query=primary_enriched,
            aspect_tag="primary_full",
            domain=primary_dom
        ))

        # 2. Domain-enriched subquery handling:
        if len(detected_domains) >= 1:
            for dom_key, dom_enrichment in detected_domains:
                focused_query = f"{cleaned[:300]} ({dom_enrichment})"
                subqueries.append(LegalSubQuery(
                    query_text=cleaned[:300],
                    enriched_query=focused_query,
                    aspect_tag=f"domain_{dom_key}",
                    domain=dom_key
                ))
                if len(subqueries) >= max_subqueries:
                    return subqueries

        # 3. Clause-level decomposition (splitting by conjunctions or punctuation)
        raw_segments = [s.strip() for s in re.split(r"[\?\!\;\n]+", cleaned) if len(s.strip()) > 6]
        sub_texts: List[str] = []
        for seg in raw_segments:
            parts = cls.CONJUNCTION_SPLIT_REGEX.split(seg)
            for part in parts:
                p = part.strip(" ,.-")
                if len(p) > 8:
                    sub_texts.append(p)

        seen_texts = {cleaned.lower()}
        for text in sub_texts:
            t_lower = text.lower()
            if t_lower in seen_texts or len(t_lower.split()) < 3:
                continue
            seen_texts.add(t_lower)

            seg_domains = cls.detect_domains(text)
            seg_dom = seg_domains[0][0] if seg_domains else primary_dom
            enriched_seg = LegalSynonymExpander.build_enriched_search_query(text)

            subqueries.append(LegalSubQuery(
                query_text=text,
                enriched_query=enriched_seg,
                aspect_tag=f"sub_aspect_{len(subqueries)}",
                domain=seg_dom
            ))

            if len(subqueries) >= max_subqueries:
                break

        return subqueries
