"""
Multi-Aspect Legal Query Decomposer.
Decomposes compound, multi-issue citizen questions into focused legal sub-queries,
ensuring comprehensive retrieval across all legal issues without topic crowding.
"""

import re
from typing import List
from pydantic import BaseModel
from src.nlp.legal_synonyms import LegalSynonymExpander


class LegalSubQuery(BaseModel):
    query_text: str
    enriched_query: str
    aspect_tag: str = "general"


class LegalQueryDecomposer:
    """Decomposes compound legal queries into focused sub-queries and enriches them with statutory terms."""

    DOMAIN_ANCHORS = [
        (r"\b(shtat|qisqar|ishdan bo['`’‘ʻʼ]?shat|mehnat|ish beruvchi|xodim|ish haqi)\b", "mehnat munosabatlari va shtat qisqarishi"),
        (r"\b(pensiya|nafaqa|yoshga doir|staj|moddiy yordam)\b", "ijtimoiy ta'minot pensiya va nafaqa"),
        (r"\b(nogiron|nogironlik|imkoniyati cheklangan|reabilitatsiya)\b", "nogironligi bo'lgan shaxslar huquqlari va kafolatlari"),
        (r"\b(homilador|bola|yolg['`’‘ʻʼ]?iz ota|yolg['`’‘ʻʼ]?iz ona|dekret)\b", "homilador ayollar va bolali ota-onalar kafolatlari"),
        (r"\b(jarima|ma['`’‘ʻʼ]?muriy|yhq|yo['`’‘ʻʼ]?l harakati|radar|prava)\b", "yo'l harakati va ma'muriy javobgarlik"),
        (r"\b(aliment|ajrashish|nikoh|meros|vasiyat)\b", "oila va fuqarolik huquqi"),
        (r"\b(jinoyat|jazo|sudlan|firibgar|pora)\b", "jinoyat qonunchiligi va javobgarlik"),
    ]

    CONJUNCTION_SPLIT_REGEX = re.compile(
        r"\b(?:hamda|shuningdek|shu bilan birga|shu jumladan|alohida|birinchi navbatda|ikkinchi navbatda)\b",
        re.IGNORECASE
    )

    @classmethod
    def decompose(cls, query: str, max_subqueries: int = 4) -> List[LegalSubQuery]:
        cleaned = query.strip()
        if not cleaned:
            return []

        # If query is short and simple (< 10 words, no multiple punctuation), keep single
        word_count = len(cleaned.split())
        has_compound_punct = bool(re.search(r"[\?\!\;\n]", cleaned))
        has_conjunctions = bool(cls.CONJUNCTION_SPLIT_REGEX.search(cleaned))

        if word_count < 10 and not has_compound_punct and not has_conjunctions:
            enriched = LegalSynonymExpander.build_enriched_search_query(cleaned)
            return [LegalSubQuery(query_text=cleaned, enriched_query=enriched, aspect_tag="primary")]

        # Detect primary domain anchor to preserve legal context across sub-clauses
        core_anchors = []
        for pat, desc in cls.DOMAIN_ANCHORS:
            if re.search(pat, cleaned, re.IGNORECASE):
                core_anchors.append(desc)
        primary_context = " ".join(core_anchors[:2])

        # Step 1: Split by sentence / punctuation boundaries
        raw_segments = [s.strip() for s in re.split(r"[\?\!\;\n]+", cleaned) if len(s.strip()) > 6]
        
        # Step 2: Split compound clauses inside segments
        sub_texts: List[str] = []
        for seg in raw_segments:
            parts = cls.CONJUNCTION_SPLIT_REGEX.split(seg)
            for part in parts:
                p = part.strip(" ,.-")
                if len(p) > 8:
                    sub_texts.append(p)

        # Step 3: Format and enrich each sub-query
        subqueries: List[LegalSubQuery] = []
        
        # Always place original query first as primary
        primary_enriched = LegalSynonymExpander.build_enriched_search_query(cleaned)
        subqueries.append(LegalSubQuery(
            query_text=cleaned,
            enriched_query=primary_enriched,
            aspect_tag="primary_full"
        ))

        seen_texts = {cleaned.lower()}
        for text in sub_texts:
            t_lower = text.lower()
            if t_lower in seen_texts or len(t_lower.split()) < 3:
                continue
            seen_texts.add(t_lower)

            # If the segment lacks context keywords, prepend primary domain context
            needs_context = True
            for pat, _ in cls.DOMAIN_ANCHORS:
                if re.search(pat, text, re.IGNORECASE):
                    needs_context = False
                    break

            effective_query = f"{primary_context} {text}" if (needs_context and primary_context) else text
            enriched_query = LegalSynonymExpander.build_enriched_search_query(effective_query)

            subqueries.append(LegalSubQuery(
                query_text=effective_query,
                enriched_query=enriched_query,
                aspect_tag=f"sub_aspect_{len(subqueries)}"
            ))

            if len(subqueries) >= max_subqueries:
                break

        return subqueries
