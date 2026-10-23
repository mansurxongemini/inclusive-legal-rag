"""
Smart Router for Legal Assistant.
Classifies incoming legal inquiries and routes them dynamically between:
- FAST_RAG (single-pass retrieval + generation, <2s) for direct factual questions;
- AGENTIC_RAG (multi-hop ReAct agent with tools, 10-20s) for compound, cross-domain, or disputative questions.
"""

import re
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel

from src.nlp.query_decomposer import LegalQueryDecomposer


class RoutingDecision(str, Enum):
    FAST_RAG = "fast_rag"
    AGENTIC_RAG = "agentic_rag"


class RouteResult(BaseModel):
    decision: RoutingDecision
    confidence: float
    reason: str
    detected_domains: List[str] = []
    complexity_factors: List[str] = []


class SmartLegalRouter:
    """Intelligent classification and dispatch between Fast RAG and Multi-Hop Agent."""

    COMPLEXITY_KEYWORDS = [
        r"\bnizo\w*", r"\bshikoyat\w*", r"\brad et\w*", r"\braddiya\w*",
        r"\bsud\w*", r"\bda['`’‘ʻʼ]?vo\w*", r"\bprokuror\w*", r"\badvokat\w*",
        r"\bmajburiy\w*", r"\bjarima\w*", r"\bundirish\w*", r"\bziddiyat\w*",
        r"\bto['`’‘ʻʼ]?lamasa\w*", r"\bbuzilsa\w*", r"\bqonunga xilof\w*",
        r"\bikkinchi tomon\w*", r"\bxususiy va davlat\w*", r"\btovon\w*",
        r"\bbaxtsiz hodisa\w*", r"\bmayiblanganda\w*", r"\bmehnat qobiliyati\w*"
    ]

    SIMPLE_FACTUAL_PATTERNS = [
        r"^qayerga murojaat\b",
        r"^qayerdan olinadi\b",
        r"^necha yoshdan\b",
        r"^qancha miqdorda\b",
        r"^muddati necha\b",
        r"^qanday hujjatlar kerak\b",
        r"^telefon raqami\b"
    ]

    def __init__(self):
        self.decomposer = LegalQueryDecomposer()
        self._compiled_complexity = [re.compile(p, re.I) for p in self.COMPLEXITY_KEYWORDS]
        self._compiled_simple = [re.compile(p, re.I) for p in self.SIMPLE_FACTUAL_PATTERNS]

    def route(self, query: str) -> RouteResult:
        clean_q = query.strip()
        if not clean_q:
            return RouteResult(
                decision=RoutingDecision.FAST_RAG,
                confidence=1.0,
                reason="Bo'sh so'rov",
                detected_domains=[]
            )

        # 1. Check multi-domain decomposition
        sub_queries = self.decomposer.decompose(clean_q)
        domains = list(dict.fromkeys([sq.domain for sq in sub_queries if sq.domain != "general"]))
        
        # 2. Check complexity signals
        complexity_factors = []
        for pat in self._compiled_complexity:
            match = pat.search(clean_q)
            if match:
                complexity_factors.append(match.group(0))

        # 3. Check simple factual signals
        is_simple_pattern = any(p.search(clean_q) for p in self._compiled_simple)

        # Decision Logic:
        # If question crosses 2 or more distinct legal domains -> AGENTIC_RAG
        if len(domains) >= 2:
            return RouteResult(
                decision=RoutingDecision.AGENTIC_RAG,
                confidence=0.95,
                reason=f"Ko'p tarmoqli savol: bir vaqtning o'zida {', '.join(domains)} sohalarini qamrab olgan.",
                detected_domains=domains,
                complexity_factors=complexity_factors
            )

        # If question contains serious dispute / conflict / damage keywords -> AGENTIC_RAG
        if len(complexity_factors) >= 1 and not is_simple_pattern and len(clean_q.split()) > 8:
            return RouteResult(
                decision=RoutingDecision.AGENTIC_RAG,
                confidence=0.90,
                reason=f"Huquqiy ziddiyat yoki nizo aniqlandi ({', '.join(complexity_factors[:3])}).",
                detected_domains=domains,
                complexity_factors=complexity_factors
            )

        # Long questions with complex circumstances (> 25 words) -> AGENTIC_RAG
        if len(clean_q.split()) >= 25:
            return RouteResult(
                decision=RoutingDecision.AGENTIC_RAG,
                confidence=0.85,
                reason="Keng ko'lamli kazuistik holat bayoni.",
                detected_domains=domains,
                complexity_factors=complexity_factors
            )

        # Default for single-aspect, short, direct questions -> FAST_RAG
        return RouteResult(
            decision=RoutingDecision.FAST_RAG,
            confidence=0.85,
            reason="Aniq va to'g'ridan-to'g'ri faktologik savol.",
            detected_domains=domains,
            complexity_factors=complexity_factors
        )
