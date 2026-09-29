"""
Module for detecting and resolving Blanket and Referential Dispositions
(Blankett- und Verweisungsnormen) across the legislation corpus.

In German and Continental legal dogmatics:
- Blankettnorm: A norm whose legal consequence or condition is completed by an external regulation
  (e.g., "Vazirlar Mahkamasi tomonidan belgilanadigan tartibda", "Yo'l harakati qoidalariga muvofiq").
- Verweisungsnorm: A norm explicitly pointing to another article or law
  (e.g., "ushbu Kodeksning 15-moddasida nazarda tutilgan tartibda").
"""

import re
from typing import Dict, List, Optional, Set
from pydantic import BaseModel


class BlanketMatch(BaseModel):
    disposition_type: str  # "blanket_government", "blanket_regulation", "statutory_reference"
    target_phrase: str
    target_doc_hint: Optional[str] = None
    target_article_hint: Optional[str] = None
    confidence: float


class BlanketAnalyzer:
    """Detects blanket conditions and external statutory references in legal texts."""

    # 1. Government Regulation Patterns (Vazirlar Mahkamasi qarorlari va nizomlari)
    GOVERNMENT_PATTERNS = [
        re.compile(
            r"(?:vazirlar\s+mahkamasi|hukumat)\s+(?:tomonidan\s+)?(?:belgilanadigan|tasdiqlanadigan|tasdiqlangan|belgilagan)\s+([a-zA-Z0-9_‘ʼ\'-]{3,80}\s+(?:tartib|nizom|qoida|reglament)[^\.,;\n]*)",
            re.IGNORECASE,
        ),
        re.compile(
            r"vazirlar\s+mahkamasining\s+(?:[\d\-]+-sonli?\s+)?(?:qarori\s+bilan\s+tasdiqlangan\s+)?([a-zA-Z0-9_‘ʼ\'-]{3,80}\s+(?:nizomi|qoidalari|tartibi))",
            re.IGNORECASE,
        ),
        re.compile(
            r"qonunchilikda\s+belgilangan\s+tartibda",
            re.IGNORECASE,
        ),
    ]

    # 2. Named Rules & Regulations (Yo'l harakati qoidalari, sanitariya qoidalari va h.k.)
    NAMED_REGULATION_PATTERNS = [
        (re.compile(r"yo[‘ʼ\']?l\s+harakati\s+qoidalari", re.IGNORECASE), "vmq_172_yhq", "Yo'l harakati qoidalari"),
        (re.compile(r"mehnatni\s+muhofaza\s+qilish\s+qoidalari", re.IGNORECASE), "reg_mehnat_muhofazasi", "Mehnatni muhofaza qilish qoidalari"),
        (re.compile(r"yong[‘ʼ\']?in\s+xavfsizligi\s+qoidalari", re.IGNORECASE), "reg_yongin_xavfsizligi", "Yong'in xavfsizligi qoidalari"),
        (re.compile(r"davlat\s+xizmatlari\s+ko[‘ʼ\']?rsatish\s+(?:ma[‘ʼ\']?muriy\s+)?reglamenti", re.IGNORECASE), "reg_davlat_xizmatlari", "Davlat xizmatlari ma'muriy reglamenti"),
        (re.compile(r"sanitariya\s+qoidalari(?:\s+va\s+normalari)?", re.IGNORECASE), "reg_sanpin", "Sanitariya qoidalari va normalari"),
        (re.compile(r"jamoat\s+tartibini\s+saqlash\s+qoidalari", re.IGNORECASE), "reg_jamoat_tartibi", "Jamoat tartibini saqlash qoidalari"),
    ]

    # 3. Explicit Intra-Code and Inter-Law References (Havolaki normalar)
    STATUTORY_REF_PATTERNS = [
        re.compile(r"ushbu\s+(?:kodeksning|qonunning)\s+(\d+(?:-\d+)*)[ -]?moddasi", re.IGNORECASE),
        re.compile(r"(?:[A-Z\w‘ʼ\'-]+)\s+kodeksining\s+(\d+(?:-\d+)*)[ -]?moddasi", re.IGNORECASE),
        re.compile(r"o[‘ʼ\']?zbekiston\s+respublikasining\s+[\"«]?([^\n\"»]{4,60})[\"»]?\s+qonuni", re.IGNORECASE),
    ]

    @classmethod
    def analyze_article_text(cls, text: str, law_slug: str = "") -> List[BlanketMatch]:
        matches: List[BlanketMatch] = []
        seen_phrases: Set[str] = set()

        # 1. Named regulations (High confidence)
        for pattern, hint_id, hint_title in cls.NAMED_REGULATION_PATTERNS:
            found = pattern.search(text)
            if found:
                phrase = found.group(0).strip()
                if phrase.lower() not in seen_phrases:
                    seen_phrases.add(phrase.lower())
                    matches.append(BlanketMatch(
                        disposition_type="blanket_named_regulation",
                        target_phrase=phrase,
                        target_doc_hint=hint_id,
                        confidence=0.95,
                    ))

        # 2. Government regulation patterns
        for pattern in cls.GOVERNMENT_PATTERNS:
            for m in pattern.finditer(text):
                phrase = m.group(0).strip()
                if phrase.lower() not in seen_phrases:
                    seen_phrases.add(phrase.lower())
                    sub = m.group(1).strip() if m.groups() else phrase
                    matches.append(BlanketMatch(
                        disposition_type="blanket_government",
                        target_phrase=phrase,
                        target_doc_hint=sub,
                        confidence=0.85,
                    ))

        # 3. Statutory cross-references
        for pattern in cls.STATUTORY_REF_PATTERNS:
            for m in pattern.finditer(text):
                phrase = m.group(0).strip()
                if phrase.lower() not in seen_phrases:
                    seen_phrases.add(phrase.lower())
                    art_num = m.group(1).strip() if m.groups() else None
                    matches.append(BlanketMatch(
                        disposition_type="statutory_reference",
                        target_phrase=phrase,
                        target_article_hint=art_num,
                        confidence=0.90,
                    ))

        return matches
