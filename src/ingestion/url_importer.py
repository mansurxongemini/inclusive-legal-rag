"""
URL Importer for Inclusive Legal RAG.
Fetches official legal acts directly from Lex.uz URLs, parses articles, and indexes them into HybridStore.
"""
import hashlib
import logging
import re
from datetime import date
from typing import List, Optional, Tuple
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from src.ingestion.localized import localized, provenance_for
from src.nlp.transliteration import cyrillic_to_latin, detect_script, normalize_apostrophes
from src.schema.canonical import (
    ArticleMetadata, ArticlePoint, ArticleStatus, CanonicalArticle, CrossReference, RefType,
)
from src.ingestion.url_safety import is_lex_uz_url
from src.storage.hybrid_store import HybridStore

logger = logging.getLogger(__name__)


class UrlImportRequest(BaseModel):
    url: str = Field(..., description="Official Lex.uz URL(s), e.g. https://lex.uz/uz/docs/-5049511 or multiline list of URLs")
    category: Optional[str] = Field(default=None, description="Optional override category. If omitted, auto-detected.")
    target_disability_types: Optional[List[str]] = Field(default=None, description="Optional disability tags")


class UrlImportResponse(BaseModel):
    success: bool
    url: str
    law_number: str
    law_title: str
    articles_imported: int
    article_ids: List[str]
    message: str
    status: str = "new"  # "new", "amended", "unchanged", "batch"
    articles_updated: int = 0
    articles_new: int = 0
    articles_unchanged: int = 0
    saved_file: Optional[str] = None


class LexUrlImporter:
    """Imports legal documents directly from a verified Lex.uz URL,
    fetching clean Word (.doc) stream, verifying hash changes, and
    selectively vectorizing only modified or newly introduced articles."""

    def __init__(self, store: Optional[HybridStore] = None, qonunlar_dir: Optional[str] = None):
        self.store = store or HybridStore()
        self.qonunlar_dir = Path(qonunlar_dir or "data/qonunlar")

    async def import_from_url(self, req: UrlImportRequest) -> UrlImportResponse:
        raw_input = req.url.strip()
        lines = [line.strip() for line in re.split(r"[\n\r,;]+", raw_input) if line.strip() and is_lex_uz_url(line.strip())]
        if len(lines) > 1:
            return await self._import_multiple_urls(lines, req)

        clean_url = lines[0] if lines else raw_input
        return await self._import_single_url(clean_url, req)

    async def _import_single_url(self, clean_url: str, req: UrlImportRequest) -> UrlImportResponse:
        parsed_url = urlparse(clean_url)
        if not is_lex_uz_url(clean_url):
            raise ValueError(f"Faqat rasmiy lex.uz havolalari qo'llab-quvvatlanadi: {clean_url}")

        # Construct clean Word document download URL with zero annotations/edits
        doc_path = parsed_url.path
        scheme = parsed_url.scheme or "https"
        download_url = f"{scheme}://{parsed_url.netloc}{doc_path}?type=doc&s527=0&s1089=0&s1104=0"

        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "uz,ru,en;q=0.9",
        }

        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            resp = await client.get(download_url, headers=headers)
            if resp.status_code == 404:
                raise ValueError(f"Lex.uz da hujjat topilmadi (HTTP 404): {clean_url}")
            if resp.status_code != 200:
                resp = await client.get(clean_url, headers=headers)
                if resp.status_code != 200:
                    raise ValueError(f"Lex.uz serveridan javob olinmadi (HTTP {resp.status_code}): {clean_url}")
            doc_bytes = resp.content
            html_text = resp.text
            content_disp = resp.headers.get("content-disposition", "")

        header_law_number: Optional[str] = None
        if content_disp:
            m_disp = re.search(
                r"((?:O[\x27\x60\u02bb\u02bc\u2018\u2019]?RQ|PQ|\u041f\u049a|VMQ|\u0412\u041c\u049a|PF|\u041f\u0424|Farmo[ny]ish)[-–—\s]*\d+(?:-[IVX]+)?)",
                content_disp,
                re.IGNORECASE
            )
            if m_disp:
                header_law_number = m_disp.group(1).replace(" ", "-")

        articles, law_number, law_title = self.parse_lex_html(
            html_text,
            clean_url,
            req,
            header_law_number=header_law_number
        )
        if not articles:
            raise ValueError(f"Ushbu havoladan huquqiy moddalar yoki bandlar ajratib olinmadi: {clean_url}")

        new_hash = hashlib.sha256(doc_bytes).hexdigest()

        qonunlar_dir = self.qonunlar_dir
        qonunlar_dir.mkdir(parents=True, exist_ok=True)

        clean_slug = re.sub(r"[^0-9a-zA-Z_\-]", "_", law_number).strip("_")
        target_file = qonunlar_dir / f"{clean_slug}.doc"

        # Check if an existing file exists for this law
        existing_file: Optional[Path] = None
        if target_file.exists():
            existing_file = target_file
        else:
            for f in qonunlar_dir.glob("*.doc"):
                if f.stem.lower() == clean_slug.lower():
                    existing_file = f
                    break

        if existing_file and existing_file.exists():
            existing_bytes = existing_file.read_bytes()
            existing_hash = hashlib.sha256(existing_bytes).hexdigest()

            if existing_hash == new_hash:
                # --- 1-HOLAT: O'ZGARISHSIZ ---
                # Hujjat allaqachon yuklangan va mutlaqo o'zgarmagan.
                # Vaqtinchalik fayl saqlanmaydi (o'chiriladi), qayta vektorlash talab etilmaydi.
                return UrlImportResponse(
                    success=True,
                    url=clean_url,
                    law_number=law_number,
                    law_title=law_title,
                    articles_imported=0,
                    article_ids=[],
                    status="unchanged",
                    articles_unchanged=len(articles),
                    saved_file=str(existing_file),
                    message=(
                        f"Hujjat ({law_number}) ilgari to'liq yuklangan va unga hech qanday o'zgartirish kiritilmagan. "
                        f"Vaqtinchalik fayl o'chirildi, qayta vektorlash talab etilmadi."
                    )
                )

            # --- 2-HOLAT: O'ZGARTIRISH KIRITILGAN ---
            # Eski fayl butunlay o'chiriladi, yangisi saqlanadi.
            # Faqatgina o'zgargan yoki yangi qo'shilgan qismlargina bazaga vektorlanadi.
            cids = [a.canonical_id for a in articles]
            existing_arts = self.store.get_articles_batch(cids)

            unchanged_arts = []
            to_index_arts = []
            updated_arts = []
            new_arts = []

            for art in articles:
                prev = existing_arts.get(art.canonical_id)
                if prev and prev.metadata.source_hash == art.metadata.source_hash:
                    unchanged_arts.append(art)
                elif prev:
                    updated_arts.append(art)
                    to_index_arts.append(art)
                else:
                    new_arts.append(art)
                    to_index_arts.append(art)

            if to_index_arts:
                await self.store.index_articles_batch(to_index_arts)

            existing_file.unlink(missing_ok=True)
            target_file.write_bytes(doc_bytes)

            return UrlImportResponse(
                success=True,
                url=clean_url,
                law_number=law_number,
                law_title=law_title,
                articles_imported=len(to_index_arts),
                article_ids=[a.canonical_id for a in to_index_arts],
                status="amended",
                articles_updated=len(updated_arts),
                articles_new=len(new_arts),
                articles_unchanged=len(unchanged_arts),
                saved_file=str(target_file),
                message=(
                    f"Hujjatda ({law_number}) o'zgarishlar aniqlandi! Eski fayl o'chirilib, yangisi saqlandi. "
                    f"Faqatgina o'zgargan ({len(updated_arts)}) va yangi ({len(new_arts)}) normalar qayta vektorlandi. "
                    f"{len(unchanged_arts)} ta o'zgarmagan norma xotirada saqlab qolindi (tejaldi)."
                )
            )

        # --- 3-HOLAT: BUTUNLAY YANGI HUJJAT ---
        await self.store.index_articles_batch(articles)
        target_file.write_bytes(doc_bytes)

        return UrlImportResponse(
            success=True,
            url=clean_url,
            law_number=law_number,
            law_title=law_title,
            articles_imported=len(articles),
            article_ids=[a.canonical_id for a in articles],
            status="new",
            articles_new=len(articles),
            articles_unchanged=0,
            saved_file=str(target_file),
            message=f"Yangi hujjat ({law_number}) Word fayl holatida saqlandi va jami {len(articles)} ta norma bazaga vektorlab kiritildi."
        )

    async def _import_multiple_urls(self, urls: List[str], req: UrlImportRequest) -> UrlImportResponse:
        total_imported = 0
        total_updated = 0
        total_new = 0
        total_unchanged = 0
        all_ids = []

        for u in urls:
            try:
                res = await self._import_single_url(u, req)
                total_imported += res.articles_imported
                total_updated += res.articles_updated
                total_new += res.articles_new
                total_unchanged += res.articles_unchanged
                all_ids.extend(res.article_ids)
            except Exception as e:
                logger.warning(f"Error importing {u}: {e}")

        summary = (
            f"Ommaviy yuklash yakunlandi: Jami {len(urls)} ta havoladan {total_new} ta yangi norma kiritildi, "
            f"{total_updated} ta norma yangilandi, {total_unchanged} ta norma o'zgarishsiz saqlandi."
        )
        return UrlImportResponse(
            success=True,
            url=f"{len(urls)} ta havola",
            law_number="OMMAVIY-YUKLASH",
            law_title=f"{len(urls)} ta Lex.uz hujjati",
            articles_imported=total_imported,
            article_ids=all_ids,
            status="batch",
            articles_updated=total_updated,
            articles_new=total_new,
            articles_unchanged=total_unchanged,
            message=summary
        )

    def parse_lex_html(
        self,
        html_text: str,
        source_url: str,
        req: UrlImportRequest,
        header_law_number: Optional[str] = None
    ) -> Tuple[List[CanonicalArticle], str, str]:
        from src.ingestion.document_inspector import DocumentInspector

        inspector = DocumentInspector()
        report = inspector.inspect_html(html_text, source_url)

        if header_law_number and (not report.law_number or report.law_number == "NORMA-LEX"):
            report.law_number = header_law_number

        if report.units:
            if req.category:
                for u in report.units:
                    u.category = req.category
            if req.target_disability_types:
                for u in report.units:
                    u.disability_types = req.target_disability_types

            articles = inspector.to_canonical_articles(report)
            if articles:
                return articles, report.law_number, report.law_title

        soup = BeautifulSoup(html_text, "html.parser")

        # 1. Clean out toolbars, popups, scripts, audio triggers
        for el in soup.select(".lx_elem2, .lx_elem3, .docNabvar, script, style, .doc-tools, .doc_tools"):
            el.decompose()

        # 2. Extract Document Title and Law Number
        title_tag = soup.find("title")
        raw_title = title_tag.get_text(strip=True) if title_tag else ""

        # Normalize title
        raw_title = re.sub(r"^[\s\xa0]+", "", raw_title)
        
        # Try to extract Law Number (e.g. O‘RQ-641, PQ-266, VMQ-864)
        num_match = re.search(r"((?:O[‘'`ʼʼ]?RQ|PQ|ПҚ|VMQ|ВМҚ|PF|ПФ|Farmo[ny]ish)[-–—\s]*\d+(?:-[IVX]+)?)", raw_title, re.IGNORECASE)
        if not num_match:
            # Fallback search inside first paragraphs of document
            num_match = re.search(r"((?:O[‘'`ʼʼ]?RQ|PQ|ПҚ|VMQ|ВМҚ|PF|ПФ)[-–—\s]*\d+)", html_text[:3000], re.IGNORECASE)

        if num_match:
            law_number = num_match.group(1).replace(" ", "-")
        else:
            son_match = re.search(r"(\d+)\s*[-–—]?\s*(?:сон|son)", raw_title, re.IGNORECASE)
            if son_match:
                law_number = f"VMQ-{son_match.group(1)}"
            else:
                law_number = "NORMA-LEX"

        # Clean law title
        law_title = raw_title
        if "—" in law_title:
            parts = law_title.split("—", 1)
            law_title = parts[0].strip()
        elif "|" in law_title:
            parts = law_title.split("|", 1)
            law_title = parts[0].strip()

        is_cyrillic = detect_script(raw_title) == "cyrillic"
        law_title_uz = cyrillic_to_latin(law_title) if is_cyrillic else normalize_apostrophes(law_title)

        law_slug = re.sub(r"[^a-z0-9_]", "_", law_number.lower()).strip("_")

        # 3. Detect category & disability types
        full_text_sample = soup.get_text()[:15000].lower()
        category = req.category or self._detect_category(full_text_sample)
        disability_types = req.target_disability_types or self._detect_disability_types(full_text_sample)

        # 4. Extract Articles
        articles: List[CanonicalArticle] = []
        doc_container = soup.select_one("div.document") or soup.find("body") or soup

        # Find all clause divs: <div class="CLAUSE_DEFAULT ..."> or paragraphs
        # In Lex.uz, clauses are wrapped in div with lx_elem or paragraph elements
        all_blocks = doc_container.find_all(["div", "p"])
        
        current_art_num: Optional[str] = None
        current_art_title: str = ""
        current_content_lines: List[str] = []

        article_header_regex = re.compile(
            r"^(?:(\d+(?:[-–—\.]\d+|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)?)\s*[-–—]?\s*(?:modda|статья|band|банд|пункт)[\.\s:]+)(.*)$",
            re.IGNORECASE
        )

        def flush_article():
            nonlocal current_art_num, current_art_title, current_content_lines
            if not current_art_num or not current_content_lines:
                return

            raw_body = "\n".join(current_content_lines).strip()
            # Remove any residual Lex.uz notes if wanted, but keep context
            if not raw_body or len(raw_body) < 15:
                current_art_num = None
                current_content_lines = []
                return

            body_script = detect_script(raw_body)
            if body_script == "cyrillic":
                body_uz = cyrillic_to_latin(raw_body)
                title_uz = cyrillic_to_latin(current_art_title)
            else:
                body_uz = normalize_apostrophes(raw_body)
                title_uz = normalize_apostrophes(current_art_title)

            clean_num = re.sub(r"[^0-9a-zA-Z_\-]", "", current_art_num)
            canonical_id = f"{law_slug}_art_{clean_num}"

            hasher = hashlib.sha256()
            hasher.update(body_uz.encode("utf-8"))
            source_hash = f"sha256:{hasher.hexdigest()[:16]}"
            today_str = date.today().isoformat()

            # Extract points
            point_pattern = re.compile(r"^\s*(\d+)[\.\)]\s+(.*)$")
            points: List[ArticlePoint] = []
            for line in current_content_lines:
                pm = point_pattern.match(line.strip())
                if pm:
                    pt_id = pm.group(1)
                    pt_txt = pm.group(2).strip()
                    pt_uz = cyrillic_to_latin(pt_txt) if body_script == "cyrillic" else normalize_apostrophes(pt_txt)
                    points.append(ArticlePoint(
                        point_id=pt_id,
                        text=localized(pt_uz, pt_txt)
                    ))

            if not points:
                points.append(ArticlePoint(
                    point_id="1",
                    text=localized(body_uz, raw_body)
                ))

            # Cross references
            cross_refs = []
            for m in re.finditer(r"(\d+)\s*[-–—]?\s*(?:modda|статья)", body_uz, re.IGNORECASE):
                t_id = f"{law_slug}_art_{m.group(1)}"
                cross_refs.append(CrossReference(ref_type=RefType.REFERS_TO, target_canonical_id=t_id))

            art = CanonicalArticle(
                canonical_id=canonical_id,
                schema_version="1.1",
                metadata=ArticleMetadata(
                    law_id=law_slug,
                    law_title=localized(law_title_uz, law_title),
                    law_number=law_number,
                    chapter_number="",
                    article_number=f"{current_art_num}-modda",
                    article_title=localized(title_uz or f"{current_art_num}-modda", current_art_title),
                    source_url=source_url,
                    effective_date=today_str,
                    last_verified_date=today_str,
                    source_hash=source_hash,
                    status=ArticleStatus.ACTIVE,
                    category=category,
                    disability_types=disability_types,
                    beneficiary_type=["person_with_disability", "individual"],
                    cross_references=cross_refs[:5],
                    embedding_model_version="baai/bge-m3",
                ),
                points=points,
                translations=localized(body_uz, raw_body),
                translation_provenance=provenance_for(localized(body_uz, raw_body))
            )
            articles.append(art)
            current_art_num = None
            current_art_title = ""
            current_content_lines = []

        seen_blocks = set()
        for block in all_blocks:
            # Avoid traversing already processed child nodes
            text = block.get_text(strip=True)
            if not text or text in seen_blocks:
                continue
            seen_blocks.add(text)

            # Skip classifier comments like [OKOZ:...]
            if text.startswith("[OKOZ:") or text.startswith("[TSZ:"):
                continue

            match = article_header_regex.match(text)
            if match:
                flush_article()
                current_art_num = match.group(1)
                current_art_title = match.group(2).strip()
            elif current_art_num:
                # Body content
                # Ignore metadata link texts like 'Oldingi tahrirga qarang'
                if "tahrirga qarang" in text.lower() or "редакции" in text.lower():
                    continue
                current_content_lines.append(text)

        flush_article()

        # Fallback if no specific "modda" was found (e.g. general resolution with numbered points)
        if not articles and all_blocks:
            articles = self._fallback_parse_paragraphs(doc_container, law_slug, law_number, law_title_uz, source_url, category, disability_types)

        return articles, law_number, law_title_uz

    def _fallback_parse_paragraphs(
        self, container, law_slug: str, law_number: str, law_title_uz: str, source_url: str, category: str, disability_types: List[str]
    ) -> List[CanonicalArticle]:
        """Parses resolutions structured as 1. 2. 3. numbered clauses and attached regulations."""
        articles = []
        clause_pattern = re.compile(r"^(\d+)[\.\)]\s+(.*)$")

        leaf_blocks = []
        seen = set()
        for el in container.find_all(["p", "div"]):
            if el.find(["p", "div"]):
                continue
            txt = el.get_text(strip=True)
            if not txt or txt in seen:
                continue
            seen.add(txt)
            if re.match(r"^\d+\.\d{2}\.\d{2}\.", txt) or txt.startswith("[OKOZ") or txt.startswith("[TSZ") or "tahrirga qarang" in txt.lower():
                continue
            leaf_blocks.append(txt)

        current_band: Optional[str] = None
        current_lines: List[str] = []
        clause_index = 0

        def flush_band():
            nonlocal current_band, current_lines, clause_index
            if not current_band or not current_lines:
                return
            full_text = "\n".join(current_lines).strip()
            if len(full_text) < 25:
                current_band = None
                current_lines = []
                return

            clause_index += 1
            body_script = detect_script(full_text)
            body_uz = cyrillic_to_latin(full_text) if body_script == "cyrillic" else normalize_apostrophes(full_text)
            cid = f"{law_slug}_band_{current_band}_{clause_index}"

            art = CanonicalArticle(
                canonical_id=cid,
                schema_version="1.1",
                metadata=ArticleMetadata(
                    law_id=law_slug,
                    law_title=localized(law_title_uz, law_title_uz),
                    law_number=law_number,
                    chapter_number="",
                    article_number=f"{current_band}-band",
                    article_title=localized(f"{current_band}-band", f"{current_band}-band"),
                    source_url=source_url,
                    effective_date=date.today().isoformat(),
                    last_verified_date=date.today().isoformat(),
                    source_hash=f"sha256:{hashlib.sha256(body_uz.encode()).hexdigest()[:16]}",
                    status=ArticleStatus.ACTIVE,
                    category=category,
                    disability_types=disability_types,
                    beneficiary_type=["person_with_disability"],
                    cross_references=[],
                    embedding_model_version="baai/bge-m3",
                ),
                points=[ArticlePoint(point_id="1", text=localized(body_uz, full_text))],
                translations=localized(body_uz, full_text),
                translation_provenance=provenance_for(localized(body_uz, full_text))
            )
            articles.append(art)
            current_band = None
            current_lines = []

        for block in leaf_blocks:
            m = clause_pattern.match(block)
            if m:
                flush_band()
                current_band = m.group(1)
                current_lines.append(block)
            elif current_band:
                current_lines.append(block)

        flush_band()
        return articles

    def _detect_category(self, text: str) -> str:
        text_low = text.lower()
        if any(w in text_low for w in ["tmek", "тмек", "tiek", "тиек", "tibbiy-ijtimoiy", "тиббий-ижтимоий"]):
            return "medical_social_expertise"
        if any(w in text_low for w in ["pensiya", "пенсия", "nafaqa", "нафақа", "kompensatsiya", "компенсация"]):
            return "pensions_and_benefits"
        if any(w in text_low for w in ["mehnat", "меҳнат", "ish o'rni", "bandlik", "бандлик", "kvota", "квота"]):
            return "labor_rights"
        if any(w in text_low for w in ["soliq", "солиқ", "imtiyoz", "имтиёз"]):
            return "tax_benefits"
        if any(w in text_low for w in ["protez", "протез", "reabilitatsiya", "реабилитация", "aravacha", "аравача"]):
            return "rehabilitation_prosthetics"
        if any(w in text_low for w in ["sanatoriy", "санаторий", "davolanish", "йўлланма", "yo'llanma"]):
            return "sanatorium_health"
        if any(w in text_low for w in ["inklyuziv", "инклюзив", "ta'lim", "таълим", "maktab", "мактаб"]):
            return "inclusive_education"
        if any(w in text_low for w in ["to'siqsiz", "тўсиқсиз", "pandus", "пандус", "shaharsozlik", "шаҳарсозлик", "infratuzilma"]):
            return "accessibility_infrastructure"
        return "disability_rights"

    def _detect_disability_types(self, text: str) -> List[str]:
        types = set()
        text_low = text.lower()
        if "1-guruh" in text_low or "i guruh" in text_low or "i гуруҳ" in text_low or "1-гуруҳ" in text_low:
            types.add("group_1")
        if "2-guruh" in text_low or "ii guruh" in text_low or "ii гуруҳ" in text_low or "2-гуруҳ" in text_low:
            types.add("group_2")
        if "3-guruh" in text_low or "iii guruh" in text_low or "iii гуруҳ" in text_low or "3-гуруҳ" in text_low:
            types.add("group_3")
        if "bola" in text_low or "бола" in text_low or "bolalikdan" in text_low:
            types.add("childhood_disability")
        if "ko'rish" in text_low or "кўриш" in text_low or "ko'zi ojiz" in text_low or "заиф" in text_low:
            types.add("visual")
        if "eshitish" in text_low or "эшитиш" in text_low or "kar" in text_low:
            types.add("hearing")
        if "harakat" in text_low or "ҳаракат" in text_low or "tayanch" in text_low or "таянч" in text_low:
            types.add("physical")
        if not types:
            types.add("general")
        return sorted(list(types))
