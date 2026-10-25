import re
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel
from src.schema.canonical import CanonicalArticle
from src.retrieval.reranker import RetrievedArticleContext


class CitationItem(BaseModel):
    index: int = 1
    canonical_id: str
    law_number: str
    law_title: str = ""
    article_number: str
    article_title: str = ""
    source_url: str
    status: str = "active"
    source_type: str = "lex"
    normative_tier: str = "Qonun"
    normative_rank: int = 3
    quote_snippet: str = ""
    confidence: float = 1.0


class ValidationResult(BaseModel):
    is_valid: bool
    sanitized_answer: str
    clean_answer: str = ""
    telegram_formatted: str = ""
    resolved_citations: List[CitationItem]
    is_refusal: bool
    unresolved_citations: List[str] = []
    warnings: List[str] = []


class CitationValidator:
    """
    Automated post-generation validation pass to ensure 100% citation faithfulness,
    NotebookLM-grade statutory grounding, and eliminate developer jargon or hallucinated claims.
    """

    # Phrases that unambiguously announce "no norm found".
    REFUSAL_TRIGGERS = [
        "aniq norma yoki qoida topilmadi",
        "aniq norma topilmadi",
        "aniq ma'lumot topilmadi",
        "не найдено точной нормы",
        "не найдено прямой нормы",
        "no specific legal provision",
        "no explicit legal provision",
    ]
    # A bare "topilmadi" is only a refusal for a short answer that cites nothing: substantive answers often say
    # that one detail (a deadline, a form) was "not found" while still citing the governing norms.
    # The refusal sentence the prompt prescribes ("cannot give an exact answer") is weak as well: a substantive answer may
    # say it about one detail of the question and still cite the governing norms.
    WEAK_REFUSAL_TRIGGERS = [
        "topilmadi", "aniq javob bera olmayman", "aniq javob bera olmaymiz", "aniq javob berib bo'lmaydi",
        "не могу дать точный ответ", "cannot give an exact answer", "can't give an exact answer",
    ]
    SUBSTANTIVE_ANSWER_MIN_CHARS = 400

    # Canonical IDs always contain underscores (law_x_art_5, pf_115_unit_3_1). Plain bracketed words such as
    # "[Eslatma]" or numeric markers "[1]" are not citations and must not count as unresolved references.
    _ID_LIKE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9\-]+)+$")

    CLAIM_MARKERS = [
        "huquqiga ega", "majbur", "taqiqlanadi", "belgilanadi", "kafolatlanadi",
        "imtiyoz beriladi", "to'lanadi", "ajratiladi", "man etiladi",
        "имеет право", "запрещается", "гарантируется", "предусматривается", "выплачивается",
        "has the right", "is prohibited", "is guaranteed", "is entitled", "shall be"
    ]

    @classmethod
    def _extract_quote_snippet(cls, article: CanonicalArticle, language: str = "uz") -> str:
        """Extracts the most pertinent 1-2 sentence verbatim excerpt from the official legal text."""
        body = article.get_text(language) or article.get_text("uz") or ""
        body_clean = re.sub(r"\s+", " ", body).strip()
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body_clean) if len(s.strip()) > 15]
        if sentences:
            snippet = sentences[0]
            if len(sentences) > 1 and len(snippet) < 120:
                snippet += " " + sentences[1]
            if len(snippet) > 260:
                snippet = snippet[:257] + "..."
            return snippet
        return body_clean[:220]

    @classmethod
    def _determine_normative_tier(cls, article: CanonicalArticle) -> Tuple[str, int]:
        """Classifies the normative hierarchy according to Uzbekistan's Law on Normative Legal Acts."""
        cat = (article.metadata.category or "").lower()
        cid = article.canonical_id.lower()
        law_title = (article.get_law_title("uz") or "").lower()
        law_num = (article.metadata.law_number or "").lower()

        if "konstitutsiya" in law_title or "constitution" in cat or "constitution" in cid:
            return "Konstitutsiya", 1
        elif "kodeks" in law_title or "code" in cat or "_code_" in cid:
            return "Kodeks", 2
        elif "o'rq" in law_num or "qonun" in law_title or cat == "law":
            return "Qonun", 3
        elif "oliy majlis" in law_title or "parliament" in cat:
            return "Oliy Majlis qarori", 4
        elif "pf-" in law_num or "farmon" in law_title or cat == "decree":
            return "Prezident Farmoni", 5
        elif "pq-" in law_num or "vmq" in cid or "qaror" in law_title or cat == "resolution":
            return "Vazirlar Mahkamasi qarori", 6
        elif "buyruq" in law_title or cat == "order":
            return "Vazirlik buyrug'i", 7
        elif "xalqaro" in law_title or cat == "treaty" or "convention" in cid:
            return "Xalqaro shartnoma", 8
        elif cat == "commentary" or "advice" in cid or "norma" in cid:
            return "Huquqiy sharh", 9
        source_type = (getattr(article.metadata, "source_type", "lex") or "lex").lower()
        if source_type == "curated" or cid.startswith("qa_"):
            return "Huquq+ javobi", 9
        if source_type == "huquqplus" or cid.startswith("hp_"):
            return "Huquq+ sharhi", 9
        return "Qonunchilik hujjati", 3

    @classmethod
    def _sanitize_developer_and_jargon(
        cls,
        text: str,
        retrieved_map: Dict[str, CanonicalArticle],
        language: str = "uz"
    ) -> str:
        """Purges any leaked developer IDs (law_..., art_...) and German legal jargon into natural Uzbek."""
        # 1. Purge raw developer IDs
        def _id_replacer(match):
            cid = match.group(1)
            art = retrieved_map.get(cid)
            if art:
                title = art.get_law_title(language) or art.metadata.law_number
                art_num = art.metadata.article_number
                return f"{title}ning {art_num}"
            return "amaldagi qonunchilik normasi"

        sanitized = re.sub(r"\b([a-z0-9_]+_art_[\w\-]+)\b", _id_replacer, text)
        sanitized = re.sub(r"\b(law_[a-z0-9_]+)\b", "qonunchilik hujjati", sanitized)

        # 2. Purge German legal terminology
        german_map = {
            r"\bSubsumtion\b": "Huquqiy tahlil",
            r"\bsubsumsiya\b": "huquqiy tatbiq",
            r"\bTatbestand\b": "Qonuniy asos",
            r"\bObersatz\b": "Bosh norma",
            r"\bUntersatz\b": "Faktik holat",
            r"\bSchlussfolgerung\b": "Xulosa",
        }
        for g_pat, uz_rep in german_map.items():
            sanitized = re.sub(g_pat, uz_rep, sanitized, flags=re.IGNORECASE)

        return sanitized

    # one bracket may cite several units: "[doc_..._p_44, doc_..._p_46]"
    _BRACKET = re.compile(r"\[([^\[\]\n]{1,600})\]")

    @classmethod
    def _bracket_ids(cls, content: str) -> List[str]:
        """The ids of one bracket, or [] when it is not a citation ("[1]", a markdown link text)."""
        tokens = [t for t in re.split(r"[,;\s]+", content.strip()) if t]
        if tokens and all(cls._ID_LIKE.match(t) for t in tokens):
            return tokens
        return []

    @classmethod
    def extract_canonical_ids(cls, text: str, valid_ids: Optional[Set[str]] = None) -> List[str]:
        bracketed = [cid for content in cls._BRACKET.findall(text) for cid in cls._bracket_ids(content)]
        pattern_matches = re.findall(r"\b([a-z0-9_]+_art_[\w\-]+)\b", text)
        direct_matches = []
        if valid_ids:
            for vid in valid_ids:
                if vid in text:
                    direct_matches.append(vid)

        combined = []
        seen = set()
        for cid in bracketed + pattern_matches + direct_matches:
            if cid not in seen:
                if valid_ids is None or cid in valid_ids:
                    seen.add(cid)
                    combined.append(cid)
        return combined

    @classmethod
    def _detect_refusal(cls, answer_text: str, retrieved_ids: Set[str]) -> bool:
        lowered = answer_text.lower().replace("ʻ", "'").replace("ʼ", "'").replace("‘", "'").replace("’", "'")
        if any(trigger in lowered for trigger in cls.REFUSAL_TRIGGERS):
            return True
        if not any(trigger in lowered for trigger in cls.WEAK_REFUSAL_TRIGGERS):
            return False

        body = re.split(r"\n\s*---", answer_text, maxsplit=1)[0].strip()  # ignore the appended disclaimer
        cites_retrieved = bool(cls.extract_canonical_ids(answer_text, retrieved_ids))
        return not (cites_retrieved and len(body) >= cls.SUBSTANTIVE_ANSWER_MIN_CHARS)

    @classmethod
    def validate_and_sanitize(
        cls,
        answer_text: str,
        retrieved_contexts: List[RetrievedArticleContext],
        language: str = "uz"
    ) -> ValidationResult:
        retrieved_map: Dict[str, CanonicalArticle] = {
            ctx.article.canonical_id: ctx.article for ctx in retrieved_contexts
        }
        retrieved_ids = set(retrieved_map.keys())

        # Check refusal
        is_refusal = cls._detect_refusal(answer_text, retrieved_ids)
        if is_refusal:
            cleaned_refusal = cls._sanitize_developer_and_jargon(answer_text, retrieved_map, language)
            return ValidationResult(
                is_valid=True,
                sanitized_answer=cleaned_refusal,
                clean_answer=cleaned_refusal,
                telegram_formatted=cleaned_refusal,
                resolved_citations=[],
                is_refusal=True,
            )

        cited_ids = cls.extract_canonical_ids(answer_text)
        unresolved = [
            cid for cid in cited_ids
            if cid not in retrieved_ids and cls._ID_LIKE.match(cid)
        ]

        # Resolve citations and preserve markdown structure
        cited_in_text = cls.extract_canonical_ids(answer_text, retrieved_ids)
        warnings = []

        no_explicit_citation = False
        sanitized_answer = answer_text
        if not cited_in_text and retrieved_contexts:
            # The model cited nothing. No norm is attached on its behalf (that would present a source the model never
            # relied on as if it were verified): the answer simply carries no citations and fails validation.
            no_explicit_citation = True
            warnings.append("no_explicit_citation: answer did not cite any retrieved norm")

        # Build ordered unique citations matching appearance
        citations: List[CitationItem] = []
        cid_to_index: Dict[str, int] = {}
        ordered_cids: List[str] = []
        for cid in cited_in_text:
            if cid not in ordered_cids and cid in retrieved_map:
                ordered_cids.append(cid)

        for idx, cid in enumerate(ordered_cids, start=1):
            art = retrieved_map.get(cid)
            if art:
                cid_to_index[cid] = idx
                tier_name, tier_rank = cls._determine_normative_tier(art)
                quote_snip = cls._extract_quote_snippet(art, language)
                citations.append(CitationItem(
                    index=idx,
                    canonical_id=art.canonical_id,
                    law_number=art.metadata.law_number,
                    law_title=art.get_law_title(language),
                    article_number=art.metadata.article_number,
                    article_title=art.get_title(language),
                    source_url=art.metadata.source_url,
                    status=art.metadata.status.value,
                    source_type=getattr(art.metadata, "source_type", "lex") or "lex",
                    normative_tier=tier_name,
                    normative_rank=tier_rank,
                    quote_snippet=quote_snip,
                    confidence=1.0,
                ))

        # Replace [cid] with [1], [2] in clean_answer
        def _replace_cid(match):
            ids = self_ids(match.group(1))
            if not ids:
                return match.group(0)
            # every id of the bracket is mapped on its own; one that was not retrieved is never shown, and it never
            # borrows the number of a retrieved id written next to it
            return "".join(f"[{cid_to_index[cid]}]" for cid in ids if cid in cid_to_index)

        self_ids = cls._bracket_ids
        clean_answer = cls._BRACKET.sub(_replace_cid, sanitized_answer)
        clean_answer = cls._sanitize_developer_and_jargon(clean_answer, retrieved_map, language)

        # Clean citation spacing: [1] [2] -> [1][2], and [1] . -> [1].
        clean_answer = re.sub(r"\]\s+\[", "][", clean_answer)
        clean_answer = re.sub(r"\]\s+([.,;:!?])", r"]\1", clean_answer)
        sanitized_answer = re.sub(r"\]\s+([.,;:!?])", r"]\1", sanitized_answer)

        # Enforce zero-emoji policy across all generated text
        sanitized_answer = cls._strip_emojis(sanitized_answer)
        clean_answer = cls._strip_emojis(clean_answer)

        # Build telegram_formatted text ready for bots with rich NotebookLM-grade citations
        bot_footer_lines = ["\n\n---\n*Asoslangan qonuniy manbalar va iqtiboslar:*"]
        for c in citations:
            tier_badge = f"[{c.normative_tier}]"
            source_type = getattr(c, "source_type", "lex")
            if source_type == "curated":
                # editorial answer: no statutory quote, and its admin-panel URL is not for citizens
                bot_footer_lines.append(f"[{c.index}] {tier_badge} {c.law_title}")
                continue
            quote_label = "Qonundan iqtibos" if source_type == "lex" else "Maqoladan"
            quote_line = f"\n   *{quote_label}:* «{c.quote_snippet}»" if c.quote_snippet else ""
            url_label = "Rasmiy manba" if source_type == "lex" else "Maqola"
            bot_footer_lines.append(
                f"[{c.index}] {tier_badge} {c.article_number} — {c.law_title} ({c.law_number}){quote_line}\n   {url_label}: {c.source_url}"
            )
        telegram_formatted = clean_answer + "\n".join(bot_footer_lines)

        if unresolved:
            warnings.append("unresolved_citations: " + ", ".join(unresolved) + " (not retrieved; removed from the answer)")
        has_lex_basis = any(getattr(c, "source_type", "lex") == "lex" for c in citations)
        if citations and not has_lex_basis:
            warnings.append("curated_without_lex_basis: answer cites only curated/huquqplus sources, no lex norm")
        if any(getattr(c, "source_type", "lex") == "huquqplus" for c in citations):
            warnings.append("huquqplus_is_commentary: huquqplus sources are commentary, not statutory basis")

        is_valid = (len(unresolved) == 0) and (len(citations) > 0 or is_refusal) and not no_explicit_citation

        return ValidationResult(
            is_valid=is_valid,
            sanitized_answer=sanitized_answer,
            clean_answer=clean_answer,
            telegram_formatted=telegram_formatted,
            resolved_citations=citations,
            is_refusal=is_refusal,
            unresolved_citations=unresolved,
            warnings=warnings,
        )

    @staticmethod
    def _strip_emojis(text: str) -> str:
        """Strips any emoji/pictograph codepoints to preserve serious legal advisory tone."""
        pattern = re.compile(
            r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[\ufe0f]"
        )
        cleaned = pattern.sub("", text)
        cleaned = re.sub(r"^(#{1,6})\s+", r"\1 ", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^(\s*[-*])\s+", r"\1 ", cleaned, flags=re.MULTILINE)
        return cleaned

