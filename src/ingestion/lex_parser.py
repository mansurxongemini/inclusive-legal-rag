import hashlib
import re
from datetime import date
from typing import Dict, List, Optional
from src.schema.canonical import (
    CanonicalArticle,
    ArticleMetadata,
    ArticlePoint,
    ArticleStatus,
    CrossReference,
    RefType,
    TranslationProvenanceType,
)
from src.nlp.transliteration import cyrillic_to_latin, detect_script, normalize_apostrophes


def extract_cross_references_from_text(text: str) -> List[CrossReference]:
    """Finds cross references to articles and laws in legal text."""
    refs = []
    # Match patterns like "15-moddasi", "15-moddasida", "O'RQ-641", "425-modda"
    matches = re.finditer(r"(\d+)\s*[-–—]?\s*(?:modda|статья)", text, re.IGNORECASE)
    seen = set()
    for m in matches:
        art_num = m.group(1)
        ref_id = f"art_{art_num}"
        if ref_id not in seen:
            seen.add(ref_id)
            refs.append(CrossReference(
                ref_type=RefType.REFERS_TO,
                target_canonical_id=ref_id
            ))
    return refs


def parse_law_text_file(text: str, filename: str) -> List[CanonicalArticle]:
    """
    Parses law text or markdown document into CanonicalArticle entities.
    Recognizes headers like:
    15-modda. Modda nomi
    1. Birinchi band...
    2. Ikkinchi band...
    """
    lines = text.splitlines()
    articles: List[CanonicalArticle] = []

    # Detect law level title or number
    law_id_base = re.sub(r"[^a-z0-9_]", "_", filename.lower().replace(".txt", "").replace(".md", ""))
    law_number = "O'RQ-CUSTOM"
    law_title_str = "O'zbekiston Respublikasi Qonuni"

    for line in lines[:10]:
        if "o'rq" in line.lower() or "zru" in line.lower():
            m = re.search(r"(?:O['`’‘ʻʼ]?RQ|ЗРУ|ZRU)[-–—\s]*(\d+)", line, re.IGNORECASE)
            if m:
                law_number = f"O'RQ-{m.group(1)}"
        if len(line.strip()) > 10 and not line.strip().startswith("#"):
            law_title_str = line.strip()

    # Regex for article header (supports sub-articles like 18-1, 41-1, 18.1)
    article_pattern = re.compile(
        r"^(?:###?\s*)?(\d+(?:[-–—\.]\d+|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)?)\s*[-–—]?\s*(?:modda|статья|article)[\.\s:]+(.*)$",
        re.IGNORECASE
    )

    current_art_num: Optional[str] = None
    current_art_title: str = ""
    current_lines: List[str] = []

    def flush_article():
        nonlocal current_art_num, current_art_title, current_lines
        if not current_art_num or not current_lines:
            return

        body_text = "\n".join(current_lines).strip()
        
        # Script normalization if Cyrillic
        if detect_script(body_text) == "cyrillic":
            body_uz = cyrillic_to_latin(body_text)
            title_uz = cyrillic_to_latin(current_art_title)
        else:
            body_uz = normalize_apostrophes(body_text)
            title_uz = normalize_apostrophes(current_art_title)

        # Extract points: "1. ...", "2. ..."
        point_pattern = re.compile(r"^\s*(\d+)[\.\)]\s+(.*)$")
        points: List[ArticlePoint] = []
        for line in current_lines:
            pm = point_pattern.match(line)
            if pm:
                pt_id = pm.group(1)
                pt_txt = pm.group(2).strip()
                if detect_script(pt_txt) == "cyrillic":
                    pt_txt = cyrillic_to_latin(pt_txt)
                points.append(ArticlePoint(
                    point_id=pt_id,
                    text={"uz": pt_txt, "ru": "", "en": ""}
                ))

        canonical_id = f"{law_id_base}_art_{current_art_num}"

        # Hash
        hasher = hashlib.sha256()
        hasher.update(body_uz.encode("utf-8"))
        source_hash = f"sha256:{hasher.hexdigest()}"

        today_str = date.today().isoformat()
        cross_refs = extract_cross_references_from_text(body_uz)

        article = CanonicalArticle(
            canonical_id=canonical_id,
            schema_version="1.1",
            metadata=ArticleMetadata(
                law_id=law_id_base,
                law_title={"uz": law_title_str, "ru": "", "en": ""},
                law_number=law_number,
                article_number=f"{current_art_num}-modda",
                article_title={"uz": title_uz, "ru": "", "en": ""},
                source_url="https://lex.uz",
                effective_date=today_str,
                last_verified_date=today_str,
                source_hash=source_hash,
                status=ArticleStatus.ACTIVE,
                category="general_legislation",
                disability_types=["general"],
                beneficiary_type=["individual"],
                cross_references=cross_refs,
                embedding_model_version="bge-m3-2025-11-18",
            ),
            points=points,
            translations={"uz": body_uz, "ru": "", "en": ""},
            translation_provenance={
                "uz": TranslationProvenanceType.OFFICIAL,
                "ru": TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                "en": TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
            }
        )
        articles.append(article)
        current_lines = []

    for line in lines:
        stripped = line.strip()
        match = article_pattern.match(stripped)
        if match:
            flush_article()
            current_art_num = match.group(1)
            current_art_title = match.group(2).strip()
        elif current_art_num:
            current_lines.append(line)

    flush_article()
    return articles
