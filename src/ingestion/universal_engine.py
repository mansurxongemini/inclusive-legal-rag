#!/usr/bin/env python3
"""
Universal Autonomous Ingestion & Legal Pipeline Engine for Uzbekistan Legislation.
Unified, modular, highly-optimized architecture that parses, normalizes, pairs (UZ + RU),
generates hybrid vector (LanceDB) & FTS5 (SQLite) indexes, and checkpoints progress.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from src.schema.canonical import (
    CanonicalArticle, ArticleMetadata, ArticlePoint, ArticleStatus, TranslationProvenanceType,
)
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient
from src.nlp.transliteration import (
    cyrillic_to_latin,
    detect_script,
    is_genuine_russian,
    normalize_apostrophes,
)

logger = logging.getLogger(__name__)


class DocumentSpec(BaseModel):
    """Specification of a normative act to be harvested and indexed."""
    slug: str
    category: str  # 'constitution', 'codes', 'laws', 'regulations', 'conventions', 'departmental'
    doc_number: str
    title_uz: str
    title_ru: str = ""
    effective_date: str = "2020-01-01"
    url_uz: str
    url_ru: Optional[str] = None
    parser_type: str = "statutory_article"  # 'statutory_article' or 'regulation_clause'
    start_element_hint: Optional[str] = None
    end_element_hint: Optional[str] = None
    max_point_number: int = 600
    beneficiary_types: List[str] = Field(default_factory=lambda: ["citizen", "legal_entity"])
    disability_types: List[str] = Field(default_factory=lambda: ["general"])


class IngestionState(BaseModel):
    """Persistent state tracking for autonomous resumption and fault tolerance."""
    last_updated: str = ""
    total_articles: int = 0
    total_documents: int = 0
    completed_slugs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    failed_slugs: Dict[str, str] = Field(default_factory=dict)


class UniversalParser:
    """Universal parser capable of extracting articles or clauses from Lex.uz HTML or raw text."""

    @staticmethod
    def table_to_markdown(tbl) -> str:
        """Converts an HTML table element into structured, readable Markdown with preserved columns."""
        rows = tbl.find_all("tr")
        if not rows:
            return ""
        matrix = []
        for r in rows:
            cells = [" ".join(c.get_text().split()).replace("|", "/") for c in r.find_all(["th", "td"])]
            if any(cells):
                matrix.append(cells)
        if not matrix:
            return ""
        max_cols = max(len(r) for r in matrix)
        if max_cols == 0:
            return ""
        for r in matrix:
            while len(r) < max_cols:
                r.append("")
        headers = [h if h else f"Ustun {idx+1}" for idx, h in enumerate(matrix[0])]
        lines = ["| " + " | ".join(headers) + " |"]
        lines.append("| " + " | ".join(["---"] * max_cols) + " |")
        for row in matrix[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    @staticmethod
    def chunk_markdown_table(md_text: str, max_rows: int = 15) -> List[Tuple[str, int, int]]:
        """
        Splits large Markdown tables into sub-tables with repeated column headers
        so that every row is preserved within the vector embedding context window.
        Returns list of (chunk_markdown, start_row, end_row).
        """
        lines = [l.strip() for l in md_text.strip().split("\n") if l.strip()]
        if len(lines) <= 2:
            return [(md_text, 1, max(1, len(lines) - 2))]
        hdr = lines[0]
        sep = lines[1]
        data_rows = lines[2:]
        if len(data_rows) <= max_rows:
            return [(md_text, 1, len(data_rows))]
        chunks = []
        for i in range(0, len(data_rows), max_rows):
            batch = data_rows[i:i + max_rows]
            chunk_str = "\n".join([hdr, sep] + batch)
            start_r = i + 1
            end_r = min(i + max_rows, len(data_rows))
            chunks.append((chunk_str, start_r, end_r))
        return chunks

    @classmethod
    def partition_document_sections(cls, elements: List[Any]) -> List[Dict[str, Any]]:
        """
        Partitions an ordered list of Lex.uz elements into logical legal sections:
        - Section 0: Main Act (Asosiy qaror / qonun matni)
        - Section 1..N: Ilovalar (Annexes), Nizomlar (Regulations), Tartiblar (Procedures), Jadvallar (Tables)
        """
        sections = []
        cur_sec = {"title": "Asosiy hujjat", "banner": "", "elements": []}
        
        i = 0
        while i < len(elements):
            el = elements[i]
            cls_list = el.get("class", [])
            txt = cls.clean_text(el.get_text())
            
            is_appl_banner = any(c in ["APPL_BANNER_LANDSCAPE_TITLE", "ACT_TITLE_APPL"] for c in cls_list)
            is_standalone_annex = bool(re.search(r'(?:^|[«\s])(?:\d+-)?(?:илова|ilova|приложение)\s*$', txt, re.IGNORECASE)) or \
                                  bool(re.search(r'қарорига\s*\d*[-–—]?\s*(?:илова|ilova)\s*$', txt, re.IGNORECASE))
            
            if (is_appl_banner or is_standalone_annex) and i > 3:
                banner_text = txt
                title_text = ""
                j = i + 1
                while j < min(i + 4, len(elements)):
                    next_cls = elements[j].get("class", [])
                    next_txt = cls.clean_text(elements[j].get_text())
                    if any(c in ["ACT_TITLE_APPL", "ACT_TITLE", "ACT_FORM"] for c in next_cls) or \
                       (any(c in ["TEXT_HEADER_DEFAULT", "TITLE"] for c in next_cls) and len(next_txt) < 140):
                        title_text = next_txt
                        j += 1
                        break
                    else:
                        break
                
                full_title = f"{banner_text} — {title_text}" if title_text else banner_text
                if cur_sec["elements"]:
                    sections.append(cur_sec)
                cur_sec = {"title": full_title, "banner": banner_text, "elements": []}
                i = j
                continue
            else:
                cur_sec["elements"].append(el)
                i += 1
                
        if cur_sec["elements"]:
            sections.append(cur_sec)
        return sections

    @staticmethod
    def derive_section_slug(title: str, sec_idx: int, existing_slugs: Set[str]) -> str:
        """Derives a collision-free, deterministic slug for each section."""
        if sec_idx == 0:
            existing_slugs.add("main")
            return "main"
        m = re.search(r'(\d+(?:-\d+)*)\s*[-–—]?\s*(?:илова|ilova|приложение)', title, re.IGNORECASE)
        if not m:
            m = re.search(r'(?:илова|ilova|приложение)\s*№?\s*(\d+(?:-\d+)*)', title, re.IGNORECASE)
        base = f"ilova_{m.group(1).replace('-', '_')}" if m else f"sec_{sec_idx}"
        candidate = base
        cnt = 1
        while candidate in existing_slugs:
            cnt += 1
            candidate = f"{base}_s{cnt}"
        existing_slugs.add(candidate)
        return candidate

    @classmethod
    def clean_soup(cls, soup: BeautifulSoup) -> BeautifulSoup:
        for tag in soup.find_all(class_=[
            "INDEXES_ON_REF", "COMMENT", "CHANGES_ORIGINS", "lx_elem2", 
            "lx_no_select", "BUTTON_BLOCK", "FOOTER", "HEADER"
        ]):
            tag.decompose()
        # Convert superscripts to hyphenated numbers (e.g. 18¹ -> 18-1)
        for sup in soup.find_all("sup"):
            stxt = sup.get_text().strip()
            if stxt.isdigit():
                sup.replace_with(f"-{stxt}")
            else:
                sup.decompose()
        # Transform HTML tables into structured Markdown tables
        for table in soup.find_all("table"):
            md = cls.table_to_markdown(table)
            if md:
                table.replace_with(soup.new_string(f"\n\n{md}\n\n"))
            else:
                table.decompose()
        return soup

    @staticmethod
    def clean_text(raw_text: str) -> str:
        t = " ".join(raw_text.split())
        t = re.sub(
            r"(?:Ҳужжатга\s*таклиф\s*юбориш|Аудиони\s*тинглаш|Ҳужжат\s*элементидан\s*ҳавола\s*олиш|"
            r"Hujjatga\s*taklif\s*yuborish|Audioni\s*tinglash|Hujjat\s*elementidan\s*havola\s*olish|"
            r"Отправить\s*предложение|Слушать\s*аудио|Получить\s*ссылку)",
            "",
            t,
            flags=re.IGNORECASE
        ).strip()
        return " ".join(t.split())

    @classmethod
    def extract_lex_language_links(cls, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Extracts official multilingual URLs from Lex.uz top language navigation bar:
          <div ... onclick="openUrl('/docs/<doc_id>')" title="На русском">Рус</div>
        Returns mapping: {'ru': 'https://lex.uz/docs/...', 'en': ..., 'uz_lat': ..., 'uz_cyrl': ...}
        """
        links = {}
        for div in soup.find_all(attrs={"title": True}):
            title = div.get("title", "").strip().lower()
            onclick = div.get("onclick", "")
            m = re.search(r"openUrl\(['\"](/docs/[^'\"]+)['\"]\)", onclick)
            if m:
                path = m.group(1)
                full_url = f"https://lex.uz{path}"
                if "русском" in title:
                    links["ru"] = full_url
                elif "english" in title:
                    links["en"] = full_url
                elif "o'zbekcha" in title or "ozbekcha" in title:
                    links["uz_lat"] = full_url
                elif "ўзбекча" in title or "uzbekcha" in title:
                    links["uz_cyrl"] = full_url
        return links

    @classmethod
    def parse_statutory_articles(
        cls,
        html_uz: str,
        spec: DocumentSpec,
        html_ru: Optional[str] = None,
    ) -> List[CanonicalArticle]:
        """Parses statutory laws and codes with 'Modda X' structure."""
        soup_uz = cls.clean_soup(BeautifulSoup(html_uz, "html.parser"))
        div_uz = soup_uz.find(id="divCont") or soup_uz.find(class_="docBody") or soup_uz.find("body")
        if not div_uz:
            return []

        # Parse Russian if available
        ru_clauses = {}
        if html_ru:
            soup_ru = cls.clean_soup(BeautifulSoup(html_ru, "html.parser"))
            div_ru = soup_ru.find(id="divCont") or soup_ru.find(class_="docBody") or soup_ru.find("body")
            if div_ru:
                ru_clauses = cls._extract_articles_from_div(div_ru, is_russian=True)

        uz_articles_raw = cls._extract_articles_from_div(div_uz, is_russian=False)
        articles: List[CanonicalArticle] = []

        for art_num, (title_raw, body_raw) in uz_articles_raw.items():
            if not body_raw.strip():
                continue

            is_cyrillic = detect_script(body_raw) == "cyrillic"
            is_russian = is_cyrillic and is_genuine_russian(body_raw)
            text_uz = cyrillic_to_latin(body_raw) if (is_cyrillic and not is_russian) else normalize_apostrophes(body_raw)
            title_uz = cyrillic_to_latin(title_raw) if (is_cyrillic and not is_russian) else normalize_apostrophes(title_raw)
            if not title_uz:
                title_uz = f"{art_num}-modda"

            text_uz_cyrl = body_raw if (is_cyrillic and not is_russian) else ""

            text_ru = ""
            title_ru = f"Статья {art_num}"
            ru_prov = TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED

            if art_num in ru_clauses:
                ru_title_extracted, ru_body_extracted = ru_clauses[art_num]
                text_ru = ru_body_extracted
                if ru_title_extracted:
                    title_ru = ru_title_extracted
                ru_prov = TranslationProvenanceType.OFFICIAL
            elif is_russian:
                text_ru = body_raw
                ru_prov = TranslationProvenanceType.OFFICIAL

            hasher = hashlib.sha256()
            hasher.update(text_uz.encode("utf-8"))
            source_hash = f"sha256:{hasher.hexdigest()}"

            translations = {"uz": text_uz, "ru": text_ru, "en": ""}
            if text_uz_cyrl:
                translations["uz_cyrl"] = text_uz_cyrl

            translation_provenance = {
                "uz": TranslationProvenanceType.OFFICIAL,
                "ru": ru_prov if text_ru else TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                "en": TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
            }
            if text_uz_cyrl:
                translation_provenance["uz_cyrl"] = TranslationProvenanceType.OFFICIAL

            law_title_dict = {
                "uz": spec.title_uz,
                "ru": spec.title_ru if (spec.title_ru and is_genuine_russian(spec.title_ru)) else "",
                "en": spec.title_uz,
            }
            if text_uz_cyrl and spec.title_uz and detect_script(spec.title_uz) == "cyrillic":
                law_title_dict["uz_cyrl"] = spec.title_uz

            art_title_dict = {"uz": title_uz, "ru": title_ru if text_ru else "", "en": f"Article {art_num}"}
            if text_uz_cyrl:
                art_title_dict["uz_cyrl"] = title_raw

            meta = ArticleMetadata(
                law_id=spec.slug,
                law_title=law_title_dict,
                law_number=spec.doc_number,
                chapter_number=None,
                article_number=f"{art_num}-modda",
                article_title=art_title_dict,
                source_url=spec.url_uz,
                effective_date=spec.effective_date,
                last_verified_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                source_hash=source_hash,
                status=ArticleStatus.ACTIVE,
                category=spec.category,
                disability_types=spec.disability_types,
                beneficiary_type=spec.beneficiary_types,
                cross_references=[],
                embedding_model_version="bge-m3-2025-11-18",
            )

            canonical_id = f"{spec.slug}_art_{art_num.replace('-', '_')}"
            pt_dict = {"uz": text_uz, "ru": text_ru, "en": ""}
            if text_uz_cyrl:
                pt_dict["uz_cyrl"] = text_uz_cyrl

            articles.append(CanonicalArticle(
                canonical_id=canonical_id,
                schema_version="1.1",
                metadata=meta,
                points=[ArticlePoint(point_id="1", text=pt_dict)],
                translations=translations,
                translation_provenance=translation_provenance
            ))

        return articles

    @classmethod
    def parse_regulation_clauses(
        cls,
        html_uz: str,
        spec: DocumentSpec,
        html_ru: Optional[str] = None,
    ) -> List[CanonicalArticle]:
        """
        Parses government resolutions, decrees, regulations, bylaws, and multi-annex acts.
        Properly partitions compound documents (Main decree + Annex 1 Nizom + Annex 2 Tartib ...)
        and chunks large tables so every row is preserved and vectorized.
        """
        soup_uz = cls.clean_soup(BeautifulSoup(html_uz, "html.parser"))
        div_uz = soup_uz.find(id="divCont") or soup_uz.find(class_="docBody") or soup_uz.find("body")
        if not div_uz:
            return []

        elements = div_uz.find_all("div", recursive=False)
        if len(elements) < 3:
            elements = div_uz.find_all(["div", "p"])
        if not elements:
            return []

        # Partition into sections (Main Act + Annexes/Regulations)
        sections = cls.partition_document_sections(elements)

        # Parse Russian sections if html_ru provided
        ru_sections = []
        if html_ru:
            soup_ru = cls.clean_soup(BeautifulSoup(html_ru, "html.parser"))
            div_ru = soup_ru.find(id="divCont") or soup_ru.find(class_="docBody") or soup_ru.find("body")
            if div_ru:
                ru_elements = div_ru.find_all("div", recursive=False)
                if len(ru_elements) < 3:
                    ru_elements = div_ru.find_all(["div", "p"])
                ru_sections = cls.partition_document_sections(ru_elements)

        pt_regex = re.compile(r"^\s*(\d+)[\.\)]\s*(.*)", re.DOTALL)
        art_regex = re.compile(
            r"^(?:(?:статья|модда|modda)\s*(\d+(?:-\d+)*)|(\d+(?:-\d+)*)\s*[-–—]?\s*(?:модда|modda|банд|band|\.|\)))\s*[\.\s:]*(.*)$",
            re.IGNORECASE | re.DOTALL
        )

        existing_slugs: Set[str] = set()
        seen_canonical_ids: Set[str] = set()
        articles: List[CanonicalArticle] = []

        for sec_idx, sec in enumerate(sections):
            sec_slug = cls.derive_section_slug(sec["title"], sec_idx, existing_slugs)
            raw_sec_title = sec["title"]
            is_sec_cyr = detect_script(raw_sec_title) == "cyrillic"
            sec_title_latin = cyrillic_to_latin(raw_sec_title) if is_sec_cyr else normalize_apostrophes(raw_sec_title)
            sec_title_latin = sec_title_latin[:140]

            sec_points: Dict[str, str] = {}
            cur_p = None
            cur_lines = []
            tbl_idx = 0

            # Match RU section if possible
            ru_sec_points: Dict[str, str] = {}
            if sec_idx < len(ru_sections):
                ru_sec = ru_sections[sec_idx]
                cur_ru_p = None
                cur_ru_lines = []
                for r_el in ru_sec["elements"]:
                    r_clean = cls.clean_text(r_el.get_text())
                    if not r_clean:
                        continue
                    m_ru = pt_regex.match(r_clean) or art_regex.match(r_clean)
                    if m_ru:
                        p_ru_num = m_ru.group(1) or m_ru.group(2)
                        if cur_ru_p is not None:
                            ru_sec_points[cur_ru_p] = "\n\n".join(cur_ru_lines)
                        cur_ru_p = p_ru_num
                        cur_ru_lines = [m_ru.group(2) if m_ru.group(2) else m_ru.group(3) or ""]
                        continue
                    if cur_ru_p is not None:
                        cur_ru_lines.append(r_clean)
                if cur_ru_p is not None:
                    ru_sec_points[cur_ru_p] = "\n\n".join(cur_ru_lines)

            for el in sec["elements"]:
                txt = cls.clean_text(el.get_text())
                if not txt:
                    continue

                # Table handling (Markdown table detected)
                if "| Ustun" in txt or "| ---" in txt:
                    tbl_idx += 1
                    chunks = cls.chunk_markdown_table(txt, max_rows=15)
                    for c_text, r_start, r_end in chunks:
                        tbl_cid = (
                            f"{spec.slug}_{sec_slug}_tbl_{tbl_idx}_p{r_start}_{r_end}"
                            if len(chunks) > 1
                            else f"{spec.slug}_{sec_slug}_tbl_{tbl_idx}"
                        )
                        if tbl_cid in seen_canonical_ids:
                            tbl_cid = f"{tbl_cid}_s{sec_idx}"
                        seen_canonical_ids.add(tbl_cid)

                        art_num = (
                            f"{sec_title_latin} jadvali, {r_start}–{r_end} qatorlar"
                            if len(chunks) > 1
                            else f"{sec_title_latin} jadvali"
                        )
                        art_title_uz = (
                            f"{sec_title_latin} jadvali ({r_start}–{r_end} qatorlar)"
                            if len(chunks) > 1
                            else f"{sec_title_latin} jadvali"
                        )

                        is_cyr = detect_script(c_text) == "cyrillic"
                        t_uz = cyrillic_to_latin(c_text) if is_cyr else normalize_apostrophes(c_text)
                        t_uz_cyrl = c_text if is_cyr else ""

                        hasher = hashlib.sha256()
                        hasher.update(t_uz.encode("utf-8"))
                        source_hash = f"sha256:{hasher.hexdigest()}"

                        translations = {"uz": t_uz, "ru": "", "en": ""}
                        if t_uz_cyrl:
                            translations["uz_cyrl"] = t_uz_cyrl

                        prov = {
                            "uz": TranslationProvenanceType.OFFICIAL,
                            "ru": TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                            "en": TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                        }
                        if t_uz_cyrl:
                            prov["uz_cyrl"] = TranslationProvenanceType.OFFICIAL

                        meta = ArticleMetadata(
                            law_id=spec.slug,
                            law_title={"uz": spec.title_uz, "ru": spec.title_ru or "", "en": spec.title_uz},
                            law_number=spec.doc_number,
                            chapter_number=None,
                            article_number=art_num[:100],
                            article_title={"uz": art_title_uz[:120], "ru": "", "en": art_title_uz[:120]},
                            source_url=spec.url_uz,
                            effective_date=spec.effective_date,
                            last_verified_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                            source_hash=source_hash,
                            status=ArticleStatus.ACTIVE,
                            category=spec.category,
                            disability_types=spec.disability_types,
                            beneficiary_type=spec.beneficiary_types,
                            cross_references=[],
                            embedding_model_version="bge-m3-2025-11-18",
                        )
                        articles.append(CanonicalArticle(
                            canonical_id=tbl_cid,
                            schema_version="1.1",
                            metadata=meta,
                            points=[ArticlePoint(point_id="1", text={"uz": t_uz, "ru": "", "en": ""})],
                            translations=translations,
                            translation_provenance=prov,
                        ))
                    continue

                m = pt_regex.match(txt) or art_regex.match(txt)
                if m:
                    p_num = m.group(1) or m.group(2)
                    if cur_p is not None:
                        sec_points[cur_p] = "\n\n".join(cur_lines)
                    cur_p = p_num
                    cur_lines = [m.group(2) if m.group(2) else m.group(3) or ""]
                    continue
                if cur_p is not None:
                    cur_lines.append(txt)

            if cur_p is not None:
                sec_points[cur_p] = "\n\n".join(cur_lines)

            # Convert points into CanonicalArticle
            for p_num, full_text in sec_points.items():
                if not full_text.strip():
                    continue

                is_cyrillic = detect_script(full_text) == "cyrillic"
                is_russian = is_cyrillic and is_genuine_russian(full_text)
                text_uz = cyrillic_to_latin(full_text) if (is_cyrillic and not is_russian) else normalize_apostrophes(full_text)
                text_uz_cyrl = full_text if (is_cyrillic and not is_russian) else ""

                text_ru = ""
                if p_num in ru_sec_points:
                    text_ru = ru_sec_points[p_num]
                elif is_russian:
                    text_ru = full_text

                art_num_str = f"{p_num}-band" if sec_slug == "main" else f"{sec_title_latin}, {p_num}-band"
                title_uz = f"{p_num}-band" if sec_slug == "main" else f"{sec_title_latin}, {p_num}-band"
                title_ru = f"Пункт {p_num}" if sec_slug == "main" else f"{sec_title_latin}, пункт {p_num}"

                hasher = hashlib.sha256()
                hasher.update(text_uz.encode("utf-8"))
                source_hash = f"sha256:{hasher.hexdigest()}"

                translations = {"uz": text_uz, "ru": text_ru, "en": ""}
                if text_uz_cyrl:
                    translations["uz_cyrl"] = text_uz_cyrl

                translation_provenance = {
                    "uz": TranslationProvenanceType.OFFICIAL,
                    "ru": TranslationProvenanceType.OFFICIAL if text_ru else TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                    "en": TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                }
                if text_uz_cyrl:
                    translation_provenance["uz_cyrl"] = TranslationProvenanceType.OFFICIAL

                canonical_id = (
                    f"{spec.slug}_art_{p_num.replace('-', '_')}"
                    if sec_slug == "main"
                    else f"{spec.slug}_{sec_slug}_art_{p_num.replace('-', '_')}"
                )
                if canonical_id in seen_canonical_ids:
                    canonical_id = f"{canonical_id}_s{sec_idx}"
                seen_canonical_ids.add(canonical_id)

                meta = ArticleMetadata(
                    law_id=spec.slug,
                    law_title={"uz": spec.title_uz, "ru": spec.title_ru or "", "en": spec.title_uz},
                    law_number=spec.doc_number,
                    chapter_number=None,
                    article_number=art_num_str[:100],
                    article_title={"uz": title_uz[:120], "ru": title_ru[:120] if text_ru else "", "en": f"Clause {p_num}"},
                    source_url=spec.url_uz,
                    effective_date=spec.effective_date,
                    last_verified_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    source_hash=source_hash,
                    status=ArticleStatus.ACTIVE,
                    category=spec.category,
                    disability_types=spec.disability_types,
                    beneficiary_type=spec.beneficiary_types,
                    cross_references=[],
                    embedding_model_version="bge-m3-2025-11-18",
                )

                articles.append(CanonicalArticle(
                    canonical_id=canonical_id,
                    schema_version="1.1",
                    metadata=meta,
                    points=[ArticlePoint(point_id="1", text={"uz": text_uz, "ru": text_ru, "en": ""})],
                    translations=translations,
                    translation_provenance=translation_provenance,
                ))

        return articles

    @classmethod
    def _extract_articles_from_div(cls, div_elem, is_russian: bool = False) -> Dict[str, Tuple[str, str]]:
        art_regex = re.compile(
            r"^(?:(?:статья|модда|modda)\s*(\d+(?:-\d+)*)|(\d+(?:-\d+)*)\s*[-–—]?\s*(?:модда|modda|банд|band|\.|\)))\s*[\.\s:]*(.*)$",
            re.IGNORECASE | re.DOTALL
        )
        articles = {}
        cur_num = None
        cur_title = ""
        cur_lines = []

        elements = div_elem.find_all(["div", "p", "tr"], recursive=False)
        if not elements or len(elements) < 3:
            elements = div_elem.find_all(["div", "p"])

        for ch in elements:
            txt = cls.clean_text(ch.get_text())
            if not txt:
                continue

            m = art_regex.match(txt)
            if m:
                if cur_num:
                    articles[cur_num] = (cur_title, "\n\n".join(cur_lines))
                cur_num = m.group(1) or m.group(2)
                cur_title = m.group(3).strip() if m.group(3) else ""
                cur_lines = []
            elif cur_num:
                cur_lines.append(txt)

        if cur_num:
            articles[cur_num] = (cur_title, "\n\n".join(cur_lines))

        return articles

    @classmethod
    def _wrap_single_article(cls, full_text: str, spec: DocumentSpec, html_ru: Optional[str] = None) -> List[CanonicalArticle]:
        is_cyrillic = detect_script(full_text) == "cyrillic"
        is_russian = is_cyrillic and is_genuine_russian(full_text)
        text_uz = cyrillic_to_latin(full_text) if (is_cyrillic and not is_russian) else normalize_apostrophes(full_text)
        text_uz_cyrl = full_text if (is_cyrillic and not is_russian) else ""

        hasher = hashlib.sha256()
        hasher.update(full_text.encode("utf-8"))
        source_hash = f"sha256:{hasher.hexdigest()}"

        meta = ArticleMetadata(
            law_id=spec.slug,
            law_title={"uz": spec.title_uz, "ru": "", "en": spec.title_uz},
            law_number=spec.doc_number,
            chapter_number=None,
            article_number="1-hujjat",
            article_title={"uz": spec.title_uz, "ru": "", "en": spec.title_uz},
            source_url=spec.url_uz,
            effective_date=spec.effective_date,
            last_verified_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            source_hash=source_hash,
            status=ArticleStatus.ACTIVE,
            category=spec.category,
            disability_types=spec.disability_types,
            beneficiary_type=spec.beneficiary_types,
            cross_references=[],
            embedding_model_version="bge-m3-2025-11-18",
        )
        canonical_id = f"{spec.slug}_art_1"
        pt_dict = {"uz": text_uz, "ru": "", "en": ""}
        if text_uz_cyrl:
            pt_dict["uz_cyrl"] = text_uz_cyrl

        return [CanonicalArticle(
            canonical_id=canonical_id,
            schema_version="1.1",
            metadata=meta,
            points=[ArticlePoint(point_id="1", text=pt_dict)],
            translations={"uz": text_uz, "ru": "", "en": ""},
            translation_provenance={
                "uz": TranslationProvenanceType.OFFICIAL,
                "ru": TranslationProvenanceType.OFFICIAL,
                "en": TranslationProvenanceType.OFFICIAL,
            }
        )]


class UniversalAutonomousEngine:
    """Master Autonomous Ingestion Engine coordinating harvesting, storage, and cataloging."""

    def __init__(
        self,
        store: Optional[HybridStore] = None,
        client: Optional[OpenRouterClient] = None,
        state_file: str = "data/store/ingestion_state.json",
        catalog_dir: str = "data/laws_catalog",
    ):
        self.store = store or HybridStore()
        self.client = client or OpenRouterClient()
        self.state_file = Path(state_file)
        self.catalog_dir = Path(catalog_dir)
        self.catalog_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> IngestionState:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return IngestionState.model_validate(json.load(f))
            except Exception as e:
                logger.warning(f"Could not load state file: {e}. Starting fresh.")
        return IngestionState()

    def _save_state(self):
        self.state.last_updated = datetime.now(timezone.utc).isoformat()
        self.state.total_articles = self.store.count()
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state.model_dump(), f, ensure_ascii=False, indent=2)

    async def ingest_spec(
        self,
        spec: DocumentSpec,
        http_client: httpx.AsyncClient,
        force_reindex: bool = False,
    ) -> int:
        """Autonomously fetches, parses, validates, and indexes a single normative act spec."""
        if not force_reindex and spec.slug in self.state.completed_slugs:
            logger.info(f"⏭ Skipping {spec.slug} (already indexed with {self.state.completed_slugs[spec.slug].get('count')} articles)")
            return 0

        logger.info(f"Processing: {spec.title_uz} [{spec.slug}]...")

        # 1. Fetch UZ text
        try:
            resp_uz = await http_client.get(spec.url_uz)
            if resp_uz.status_code != 200:
                raise RuntimeError(f"HTTP {resp_uz.status_code} on {spec.url_uz}")
            html_uz = resp_uz.text
        except Exception as e:
            logger.error(f"Failed to fetch UZ for {spec.slug}: {e}")
            self.state.failed_slugs[spec.slug] = str(e)
            self._save_state()
            return 0

        # 2. Extract official language URLs from Lex.uz page header (На русском, In english, O'zbekcha)
        soup_uz_raw = BeautifulSoup(html_uz, "html.parser")
        lang_links = UniversalParser.extract_lex_language_links(soup_uz_raw)

        # Auto-extract real title from Lex.uz HTML if placeholder was passed
        if spec.title_uz.startswith("Lex.uz Hujjat #") or not spec.title_uz:
            extracted_title = ""
            if soup_uz_raw.title and len(soup_uz_raw.title.get_text().strip()) > 5:
                extracted_title = UniversalParser.clean_text(soup_uz_raw.title.get_text())
            else:
                act_title_elem = soup_uz_raw.find(class_="ACT_TITLE") or soup_uz_raw.find(class_="ACT_NAME")
                if act_title_elem:
                    extracted_title = UniversalParser.clean_text(act_title_elem.get_text())
            if extracted_title:
                if detect_script(extracted_title) == "cyrillic" and not is_genuine_russian(extracted_title):
                    spec.title_uz = cyrillic_to_latin(extracted_title)
                else:
                    spec.title_uz = extracted_title

        # 3. Fetch official RU text if discovered or provided
        html_ru = None
        target_ru_url = spec.url_ru or lang_links.get("ru")
        if target_ru_url:
            try:
                resp_ru = await http_client.get(target_ru_url)
                if resp_ru.status_code == 200:
                    html_ru = resp_ru.text
            except Exception as e:
                logger.warning(f"Could not fetch official RU for {spec.slug} from {target_ru_url}: {e}")

        # 4. Parse with dual-mode evaluation: extract richest article/clause set
        articles_stat = UniversalParser.parse_statutory_articles(html_uz, spec, html_ru)
        articles_reg = UniversalParser.parse_regulation_clauses(html_uz, spec, html_ru)

        if spec.parser_type == "regulation_clause":
            articles = articles_reg if len(articles_reg) >= len(articles_stat) else articles_stat
        else:
            articles = articles_stat if len(articles_stat) >= len(articles_reg) else articles_reg

        if not articles:
            articles = articles_reg or articles_stat

        if not articles:
            # Fallback: treat whole document content as single clause/article so no document is lost
            div_uz = soup_uz_raw.find(id="divCont") or soup_uz_raw.find(class_="docBody") or soup_uz_raw.find("body")
            if div_uz:
                full_text = UniversalParser.clean_text(div_uz.get_text())
                if full_text and len(full_text) > 40:
                    articles = UniversalParser._wrap_single_article(full_text, spec, html_ru)

        if not articles:
            logger.warning(f"No articles parsed for {spec.slug}")
            self.state.failed_slugs[spec.slug] = "Zero articles parsed"
            self._save_state()
            return 0

        logger.info(f"Extracted {len(articles)} articles/clauses for {spec.slug}")

        # 5. Save cache catalog
        catalog_path = self.catalog_dir / f"{spec.slug}.json"
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump([a.model_dump() for a in articles], f, ensure_ascii=False, indent=2)

        # 5. Batch index into LanceDB and SQLite FTS5
        await self.store.index_articles_batch(
            articles, client=self.client, batch_size=20
        )

        # 6. Update state
        self.state.completed_slugs[spec.slug] = {
            "title": spec.title_uz,
            "category": spec.category,
            "count": len(articles),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        if spec.slug in self.state.failed_slugs:
            del self.state.failed_slugs[spec.slug]
        self._save_state()

        logger.info(f"Successfully indexed {len(articles)} articles for {spec.slug}. Total store: {self.store.count()}")
        return len(articles)

    async def run_pipeline(
        self,
        specs: List[DocumentSpec],
        concurrency: int = 1,
        force_reindex: bool = False,
    ) -> Dict[str, Any]:
        """Runs the autonomous pipeline through a list of DocumentSpecs."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Uzbekistan Legal Research Platform; contact@legal-rag.uz)",
            "Accept": "text/html,application/xhtml+xml",
        }
        total_indexed = 0
        started_at = time.time()

        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=headers) as http_client:
            for spec in specs:
                cnt = await self.ingest_spec(spec, http_client, force_reindex=force_reindex)
                total_indexed += cnt
                await asyncio.sleep(0.5)  # Polite crawling delay

        elapsed = time.time() - started_at
        return {
            "total_specs": len(specs),
            "total_indexed": total_indexed,
            "elapsed_seconds": round(elapsed, 2),
            "store_total": self.store.count(),
        }


# =========================================================================
# STANDARD NORMATIVE ACT REGISTRY
# High-impact acts completing the legal corpus across all citizen domains
# =========================================================================

CORE_REGULATIONS_REGISTRY: List[DocumentSpec] = [
    DocumentSpec(
        slug="vmq_172_yhq",
        category="regulations",
        doc_number="172-sonli VMQ",
        title_uz="Yo'l harakati qoidalari",
        title_ru="Правила дорожного движения",
        effective_date="2022-05-01",
        url_uz="https://lex.uz/docs/5953883",
        url_ru="https://lex.uz/docs/5953887",
        parser_type="regulation_clause",
        max_point_number=200,
        beneficiary_types=["driver", "pedestrian", "citizen"],
    ),
    DocumentSpec(
        slug="vmq_592_pension",
        category="regulations",
        doc_number="592-sonli VMQ",
        title_uz="Davlat pensiyalarini tayinlash va to'lash tartibi to'g'risidagi Nizom",
        title_ru="Положение о порядке назначения и выплаты государственных пенсий",
        effective_date="2022-10-13",
        url_uz="https://lex.uz/docs/6236060",
        url_ru=None,
        parser_type="regulation_clause",
        start_element_hint="Давлат пенсияларини тайинлаш ва тўлаш тартиби тўғрисида",
        end_element_hint="низомга 1-илова",
        max_point_number=250,
        beneficiary_types=["retiree", "person_with_disability", "family_survivor", "citizen"],
        disability_types=["group_1", "group_2", "group_3", "general"],
    ),
    DocumentSpec(
        slug="vmq_35_allowance",
        category="regulations",
        doc_number="35-sonli VMQ (3-ilova)",
        title_uz="Ijtimoiy reyestrga kiritilgan oilalarga bolalar nafaqasi va moddiy yordam tayinlash va to'lash tartibi to'g'risidagi Nizom",
        title_ru="Положение о порядке назначения и выплаты детских пособий и материальной помощи семьям, включенным в Социальный реестр",
        effective_date="2026-02-01",
        url_uz="https://lex.uz/docs/-8027513",
        url_ru=None,
        parser_type="regulation_clause",
        start_element_hint="qaroriga3-ILOVA",
        end_element_hint="nizomga1-ILOVA",
        max_point_number=100,
        beneficiary_types=["low_income_family", "child", "citizen"],
    ),
    DocumentSpec(
        slug="vmq_35_registry",
        category="regulations",
        doc_number="35-sonli VMQ (1-ilova)",
        title_uz="Ijtimoiy reyestrni yuritish tartibi to'g'risidagi Nizom",
        title_ru="Положение о порядке ведения Социального реестра",
        effective_date="2026-02-01",
        url_uz="https://lex.uz/docs/-8027513",
        url_ru=None,
        parser_type="regulation_clause",
        start_element_hint="35-son qaroriga1-ILOVA",
        end_element_hint="Ijtimoiy reyestrni yuritish tartibi toʻgʻrisidagi nizomga1-ILOVA",
        max_point_number=100,
        beneficiary_types=["low_income_family", "vulnerable_citizen", "citizen"],
    ),
    DocumentSpec(
        slug="vmq_965_quota",
        category="regulations",
        doc_number="965-sonli VMQ",
        title_uz="Ijtimoiy muhofazaga muhtoj shaxslarni ishga joylashtirish uchun ish o'rinlarining eng kam sonini belgilash va zaxiraga qo'yish tartibi to'g'risidagi Nizom",
        title_ru="Положение о порядке установления минимального количества и резервирования рабочих мест для трудоустройства лиц, нуждающихся в социальной защите",
        effective_date="2018-01-01",
        url_uz="https://lex.uz/docs/-3448292",
        url_ru="https://lex.uz/docs/3448292",
        parser_type="regulation_clause",
        start_element_hint="965-son qarorig",
        end_element_hint="nizomga 1-ilova",
        max_point_number=60,
        beneficiary_types=["person_with_disability", "job_seeker", "vulnerable_citizen"],
        disability_types=["group_1", "group_2", "general"],
    ),
    DocumentSpec(
        slug="vmq_408_license",
        category="regulations",
        doc_number="408-sonli VMQ (2-1-ilova)",
        title_uz="Milliy haydovchilik guvohnomasini berish tartibi to'g'risidagi Nizom",
        title_ru="Положение о порядке выдачи национального водительского удостоверения",
        effective_date="2018-06-06",
        url_uz="https://lex.uz/docs/-3765833",
        url_ru="https://lex.uz/docs/3765833",
        parser_type="regulation_clause",
        start_element_hint="408-son qaroriga 2-1-ILOVA",
        end_element_hint="SXEMASI",
        max_point_number=100,
        beneficiary_types=["driver", "citizen"],
    ),
]
