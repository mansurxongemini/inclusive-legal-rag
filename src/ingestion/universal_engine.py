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
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from src.schema.canonical import (
    CanonicalArticle,
    ArticleMetadata,
    ArticlePoint,
    ArticleStatus,
    CrossReference,
    RefType,
    TranslationProvenanceType,
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
    def clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
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
        return soup

    @staticmethod
    def clean_text(raw_text: str) -> str:
        t = " ".join(raw_text.split())
        t = re.sub(
            r"^(?:Ҳужжатга\s+таклиф\s+юбориш|Аудиони\s+тинглаш|Ҳужжат\s+элементидан\s+ҳавола\s+олиш|"
            r"Hujjatga\s+taklif\s+yuborish|Audioni\s+tinglash|Hujjat\s+elementidan\s+havola\s+olish|"
            r"Отправить\s+предложение|Слушать\s+аудио|Получить\s+ссылку)+",
            "",
            t
        ).strip()
        return t

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
        """Parses government resolutions, regulations, and bylaws with numbered points ('1-band', '1.', '2.')."""
        soup_uz = cls.clean_soup(BeautifulSoup(html_uz, "html.parser"))
        div_uz = soup_uz.find(id="divCont") or soup_uz.find(class_="docBody") or soup_uz.find("body")
        if not div_uz:
            return []

        elements = div_uz.find_all("div", recursive=False)

        # Detect boundaries if specified
        start_idx = 0
        end_idx = len(elements)

        if spec.start_element_hint:
            hint_lower = spec.start_element_hint.lower()
            for i, el in enumerate(elements):
                if hint_lower in el.get_text().lower():
                    start_idx = i
                    break

        if spec.end_element_hint:
            hint_lower = spec.end_element_hint.lower()
            for i in range(start_idx + 5, len(elements)):
                el = elements[i]
                cls_list = el.get("class", [])
                if any(c in ["APPL_BANNER_LANDSCAPE_TITLE", "ACT_TITLE_APPL"] for c in cls_list):
                    if hint_lower in el.get_text().lower() or "ilova" in el.get_text().lower():
                        end_idx = i
                        break

        pt_regex = re.compile(r"^\s*(\d+)[\.\)]\s*(.*)", re.DOTALL)
        points_raw: Dict[int, str] = {}
        cur_p = None
        cur_lines = []

        for idx in range(start_idx, end_idx):
            el = elements[idx]
            cls_list = el.get("class", [])
            # Stop if another attachment begins after start
            if idx > start_idx + 10 and any(c in ["APPL_BANNER_LANDSCAPE_TITLE", "ACT_TITLE_APPL"] for c in cls_list):
                txt_check = el.get_text().lower()
                if "ilova" in txt_check or "nizomga" in txt_check:
                    break

            clean_t = cls.clean_text(el.get_text())
            if not clean_t:
                continue

            m = pt_regex.match(clean_t)
            if m:
                p_num = int(m.group(1))
                if p_num <= spec.max_point_number:
                    if cur_p is not None:
                        points_raw[cur_p] = "\n\n".join(cur_lines)
                    cur_p = p_num
                    cur_lines = [m.group(2)]
                    continue

            if cur_p is not None:
                cur_lines.append(clean_t)

        if cur_p is not None:
            points_raw[cur_p] = "\n\n".join(cur_lines)

        # Parse Russian regulation clauses if html_ru provided
        ru_points: Dict[int, str] = {}
        if html_ru:
            soup_ru = cls.clean_soup(BeautifulSoup(html_ru, "html.parser"))
            div_ru = soup_ru.find(id="divCont") or soup_ru.find(class_="docBody") or soup_ru.find("body")
            if div_ru:
                ru_elements = div_ru.find_all("div", recursive=False)
                cur_ru_p = None
                cur_ru_lines = []
                for el in ru_elements:
                    clean_t = cls.clean_text(el.get_text())
                    if not clean_t:
                        continue
                    m = pt_regex.match(clean_t)
                    if m:
                        p_num = int(m.group(1))
                        if cur_ru_p is not None:
                            ru_points[cur_ru_p] = "\n\n".join(cur_ru_lines)
                        cur_ru_p = p_num
                        cur_ru_lines = [m.group(2)]
                        continue
                    if cur_ru_p is not None:
                        cur_ru_lines.append(clean_t)
                if cur_ru_p is not None:
                    ru_points[cur_ru_p] = "\n\n".join(cur_ru_lines)

        articles: List[CanonicalArticle] = []
        for p_num, full_text in points_raw.items():
            if not full_text.strip():
                continue

            is_cyrillic = detect_script(full_text) == "cyrillic"
            is_russian = is_cyrillic and is_genuine_russian(full_text)
            text_uz = cyrillic_to_latin(full_text) if (is_cyrillic and not is_russian) else normalize_apostrophes(full_text)
            text_uz_cyrl = full_text if (is_cyrillic and not is_russian) else ""

            text_ru = ""
            title_uz = f"{p_num}-band"
            title_ru = f"Пункт {p_num}"
            ru_prov = TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED

            if p_num in ru_points:
                text_ru = ru_points[p_num]
                ru_prov = TranslationProvenanceType.OFFICIAL
            elif is_russian:
                text_ru = full_text
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

            art_title_dict = {"uz": title_uz, "ru": title_ru if text_ru else "", "en": f"Clause {p_num}"}
            if text_uz_cyrl:
                art_title_dict["uz_cyrl"] = f"{p_num}-банд"

            meta = ArticleMetadata(
                law_id=spec.slug,
                law_title=law_title_dict,
                law_number=spec.doc_number,
                chapter_number=None,
                article_number=f"{p_num}-band",
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

            canonical_id = f"{spec.slug}_art_{p_num}"
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
    def _extract_articles_from_div(cls, div_elem, is_russian: bool = False) -> Dict[str, Tuple[str, str]]:
        art_regex = re.compile(r"^(?:статья|модда|modda)\s*(\d+(?:-\d+)*)[\.\s:]*(.*)$", re.IGNORECASE)
        articles = {}
        cur_num = None
        cur_title = ""
        cur_lines = []

        for ch in div_elem.find_all("div", recursive=False):
            txt = cls.clean_text(ch.get_text())
            if not txt:
                continue

            m = art_regex.match(txt)
            if m:
                if cur_num:
                    articles[cur_num] = (cur_title, "\n\n".join(cur_lines))
                cur_num = m.group(1)
                cur_title = m.group(2).strip()
                cur_lines = []
            elif cur_num:
                cur_lines.append(txt)

        if cur_num:
            articles[cur_num] = (cur_title, "\n\n".join(cur_lines))

        return articles


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
            logger.info(f"⏭️ Skipping {spec.slug} (already indexed with {self.state.completed_slugs[spec.slug].get('count')} articles)")
            return 0

        logger.info(f"📥 Processing: {spec.title_uz} [{spec.slug}]...")

        # 1. Fetch UZ text
        try:
            resp_uz = await http_client.get(spec.url_uz)
            if resp_uz.status_code != 200:
                raise RuntimeError(f"HTTP {resp_uz.status_code} on {spec.url_uz}")
            html_uz = resp_uz.text
        except Exception as e:
            logger.error(f"❌ Failed to fetch UZ for {spec.slug}: {e}")
            self.state.failed_slugs[spec.slug] = str(e)
            self._save_state()
            return 0

        # 2. Extract official language URLs from Lex.uz page header (На русском, In english, O'zbekcha)
        soup_uz_raw = BeautifulSoup(html_uz, "html.parser")
        lang_links = UniversalParser.extract_lex_language_links(soup_uz_raw)

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

        # 3. Parse based on spec type
        if spec.parser_type == "regulation_clause":
            articles = UniversalParser.parse_regulation_clauses(html_uz, spec, html_ru)
        else:
            articles = UniversalParser.parse_statutory_articles(html_uz, spec, html_ru)

        if not articles:
            logger.warning(f"⚠️ No articles parsed for {spec.slug}")
            self.state.failed_slugs[spec.slug] = "Zero articles parsed"
            self._save_state()
            return 0

        logger.info(f"✅ Extracted {len(articles)} articles/clauses for {spec.slug}")

        # 4. Save cache catalog
        catalog_path = self.catalog_dir / f"{spec.slug}.json"
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump([a.model_dump() for a in articles], f, ensure_ascii=False, indent=2)

        # 5. Batch index into LanceDB and SQLite FTS5
        indexed_count = await self.store.index_articles_batch(
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

        logger.info(f"🎯 Successfully indexed {len(articles)} articles for {spec.slug}. Total store: {self.store.count()}")
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
