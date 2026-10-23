"""
Document Inspector & Ingestion Visualizer for Inclusive Legal RAG.
Inspects, parses, and displays exactly what text and table representations are
sent into the BGE-M3 embedding model from any Lex.uz legal act.
"""
import hashlib
import logging
import re
from datetime import date
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from src.ingestion.url_safety import is_lex_uz_url
from src.ingestion.localized import localized, provenance_for
from src.nlp.transliteration import cyrillic_to_latin, detect_script, normalize_apostrophes

logger = logging.getLogger(__name__)


CATEGORY_NAMES_UZ = {
    "disability_rights": "Nogironlik huquqlari va umumiy kafolatlar",
    "pensions_and_benefits": "Pensiyalar, nafaqalar va moddiy to'lovlar",
    "labor_rights": "Mehnat huquqlari va ish o'rni kvotalari",
    "medical_social_expertise": "Tibbiy-ijtimoiy ekspertiza (TMEK)",
    "tax_benefits": "Soliq va davlat boji imtiyozlari",
    "transport_benefits": "Transportdan imtiyozli foydalanish",
    "rehabilitation_prosthetics": "Reabilitatsiya va protez-ortopediya vositalari",
    "sanatorium_health": "Sanatoriy-kurortda bepul davolanish",
    "inclusive_education": "Inklyuziv ta'lim va grant kvotalari",
    "accessibility_infrastructure": "To'siqsiz muhit va shaharsozlik",
    "court_appeal": "Sud himoyasi va qarorlar ustidan shikoyat qilish",
    "international_treaty": "BMT Konvensiyasi va xalqaro me'yorlar",
}


class InspectUnit(BaseModel):
    order: int
    unit_id: str
    unit_type: str  # "modda", "band", "jadval", "preambula", "nizom"
    unit_num: Optional[str] = None
    title: str
    raw_source_preview: str
    is_table: bool = False
    html_table: Optional[str] = None
    markdown_table: Optional[str] = None
    exact_bge_prompt: str
    approx_tokens: int
    category: str
    clause_topic: Optional[str] = None
    clause_topic_name: Optional[str] = None
    doc_category_name: Optional[str] = None
    disability_types: List[str]


class DocumentInspectionReport(BaseModel):
    success: bool
    url: str
    law_number: str
    law_title: str
    effective_date: str
    total_units: int
    tables_count: int
    clauses_count: int
    units: List[InspectUnit]
    message: str


class DocumentInspector:
    """Provides transparent, step-by-step insight into how legal documents and tables are vectorized."""

    def __init__(self):
        pass

    async def inspect_url(self, url: str) -> DocumentInspectionReport:
        clean_url = url.strip()
        if not is_lex_uz_url(clean_url):
            raise ValueError(f"Faqat rasmiy lex.uz havolalari qo'llab-quvvatlanadi: {clean_url}")

        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "uz,ru,en;q=0.9",
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(clean_url, headers=headers)
            if resp.status_code != 200:
                raise ValueError(f"Lex.uz dan javob olinmadi (HTTP {resp.status_code}): {clean_url}")
            html_text = resp.text

        return self.inspect_html(html_text, clean_url)

    def inspect_html(self, html_text: str, source_url: str) -> DocumentInspectionReport:
        soup = BeautifulSoup(html_text, "html.parser")

        # 1. Clean out toolbars, scripts, audio triggers
        for el in soup.select(".lx_elem2, .lx_elem3, .docNabvar, script, style, .doc-tools, .doc_tools"):
            el.decompose()

        # 2. Extract Document Title and Law Number
        title_tag = soup.find("title")
        raw_title = title_tag.get_text(strip=True) if title_tag else ""
        raw_title = re.sub(r"^[\s\xa0]+", "", raw_title)

        num_match = re.search(r"((?:O[‘'`ʼʼ]?RQ|PQ|ПҚ|VMQ|ВМҚ|PF|ПФ|Farmo[ny]ish)[-–—\s]*\d+(?:-[IVX]+)?)", raw_title, re.IGNORECASE)
        if not num_match:
            son_match = re.search(r"(\d+)\s*[-–—]?\s*(?:сон|son)", raw_title, re.IGNORECASE)
            if son_match:
                law_number = f"VMQ-{son_match.group(1)}"
            else:
                # Fallback: check document text (especially the end or beginning of the law)
                sample_full = soup.get_text()
                law_pat = re.compile(
                    r"((?:O[\x27\x60\u02bb\u02bc\u2018\u2019]?RQ|PQ|\u041f\u049a|VMQ|\u0412\u041c\u049a|PF|\u041f\u0424|Farmo[ny]ish)[-–—\s]*\d+(?:-[IVX]+)?)",
                    re.IGNORECASE
                )
                text_matches = list(law_pat.finditer(sample_full))
                if text_matches:
                    law_number = text_matches[-1].group(1).replace(" ", "-")
                else:
                    law_number = "NORMA-LEX"
        else:
            law_number = num_match.group(1).replace(" ", "-")

        law_title = raw_title
        if not law_title or law_title.startswith("lex.uz"):
            # Extract first meaningful title from document tags
            for el in soup.find_all(["p", "div", "h1", "h2", "h3"])[:15]:
                t = el.get_text(strip=True)
                if len(t) > 10 and len(t) < 250:
                    t_low = t.lower()
                    if any(k in t_low for k in ["respublikasining qonuni", "qarori", "farmoni", "buyrug‘i"]):
                        continue
                    if any(k in t_low for k in ["qonunchilik palatasi", "senat", "prezident", "hujjat:"]):
                        continue
                    law_title = t
                    break

        if "—" in law_title:
            law_title = law_title.split("—", 1)[0].strip()
        elif "|" in law_title:
            law_title = law_title.split("|", 1)[0].strip()

        is_cyrillic = detect_script(law_title) == "cyrillic"
        law_title_uz = cyrillic_to_latin(law_title) if is_cyrillic else normalize_apostrophes(law_title)

        # 3. Detect category & disability types
        full_sample = soup.get_text()[:15000].lower()
        doc_category = self._detect_category(full_sample, law_title=law_title_uz)
        doc_cat_name = CATEGORY_NAMES_UZ.get(doc_category, doc_category)
        doc_disability = self._detect_disability_types(full_sample)

        doc_container = soup.select_one("div.document") or soup.find("body") or soup

        units: List[InspectUnit] = []
        tables_count = 0
        clauses_count = 0
        order_idx = 1

        # We traverse the document nodes to preserve chronological reading order (articles, clauses, tables)
        # Find all direct or major elements: paragraphs, headings, and tables
        elements = doc_container.find_all(["p", "div", "table"])
        
        # Regex patterns
        clause_pattern = re.compile(r"^(\d+)[\.\)]\s+(.*)$")
        article_header_regex = re.compile(
            r"^(?:(\d+(?:[-–—\.]\d+|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)?)\s*[-–—]?\s*(?:modda|статья|band|банд|пункт)[\.\s:]+)(.*)$",
            re.IGNORECASE
        )

        seen_tables = set()
        seen_texts = set()

        current_clause_num: Optional[str] = None
        current_clause_title: str = ""
        current_clause_type: str = "band"
        current_clause_lines: List[str] = []

        def flush_current_clause():
            nonlocal current_clause_num, current_clause_title, current_clause_type, current_clause_lines, order_idx, clauses_count
            if not current_clause_num or not current_clause_lines:
                return

            full_body = "\n".join(current_clause_lines).strip()
            if len(full_body) < 20:
                current_clause_num = None
                current_clause_lines = []
                return

            clauses_count += 1
            body_script = detect_script(full_body)
            body_uz = cyrillic_to_latin(full_body) if body_script == "cyrillic" else normalize_apostrophes(full_body)
            title_uz = cyrillic_to_latin(current_clause_title) if body_script == "cyrillic" else normalize_apostrophes(current_clause_title)

            # Detect clause-specific topic
            clause_slug, clause_name_uz = self._detect_clause_topic(full_body, doc_category)

            # Construct the EXACT prompt string formatted for BGE-M3 embedding:
            clause_label = f"{current_clause_num}-{current_clause_type}"
            display_title = f"{clause_label}. {title_uz}" if title_uz else clause_label

            exact_bge_prompt = (
                f"Hujjat: {law_number}. {law_title_uz}\n"
                f"Norma: {display_title}\n"
                f"Hujjat sohasi: {doc_cat_name}\n"
                f"Norma sohasi: {clause_name_uz}\n"
                f"Qoidalar:\n{body_uz}"
            )

            unit = InspectUnit(
                order=order_idx,
                unit_id=f"unit_{order_idx}_{re.sub(r'[^a-zA-Z0-9]', '_', current_clause_num)}",
                unit_type=current_clause_type,
                unit_num=clause_label,
                title=display_title,
                raw_source_preview=full_body[:500] + ("..." if len(full_body) > 500 else ""),
                is_table=False,
                exact_bge_prompt=exact_bge_prompt,
                approx_tokens=len(exact_bge_prompt.split()),
                category=doc_category,
                clause_topic=clause_slug,
                clause_topic_name=clause_name_uz,
                doc_category_name=doc_cat_name,
                disability_types=doc_disability,
            )
            units.append(unit)
            order_idx += 1
            current_clause_num = None
            current_clause_title = ""
            current_clause_type = "band"
            current_clause_lines = []

        for el in elements:
            # Handle Table
            if el.name == "table":
                # Flush pending clause before table
                flush_current_clause()
                table_key = str(el)[:100]
                if table_key in seen_tables:
                    continue
                seen_tables.add(table_key)

                md_table, semantic_text, raw_html_table = self._process_table(el)
                if not md_table:
                    continue

                tables_count += 1
                table_num = f"{tables_count}-jadval"
                table_title = f"{table_num}: Reja va bosqichlar jadvali"
                table_topic_name = "Reja, taqsimot va mezonlar jadvali"

                exact_bge_prompt = (
                    f"Hujjat: {law_number}. {law_title_uz}\n"
                    f"Jadval: {table_title}\n"
                    f"Hujjat sohasi: {doc_cat_name}\n"
                    f"Norma sohasi: {table_topic_name}\n"
                    f"Jadval ko'rinishi (Markdown):\n{md_table}\n\n"
                    f"Semantik qatorlar (AI tahlili uchun):\n{semantic_text}"
                )

                unit = InspectUnit(
                    order=order_idx,
                    unit_id=f"unit_{order_idx}_table_{tables_count}",
                    unit_type="jadval",
                    unit_num=table_num,
                    title=table_title,
                    raw_source_preview=semantic_text[:500] + "...",
                    is_table=True,
                    html_table=raw_html_table,
                    markdown_table=md_table,
                    exact_bge_prompt=exact_bge_prompt,
                    approx_tokens=len(exact_bge_prompt.split()),
                    category=doc_category,
                    clause_topic="schedule_table",
                    clause_topic_name=table_topic_name,
                    doc_category_name=doc_cat_name,
                    disability_types=doc_disability,
                )
                units.append(unit)
                order_idx += 1
                continue

            # Skip containers that have children p/div to prevent duplicates
            if el.find(["p", "div", "table"]):
                continue

            txt = el.get_text(strip=True)
            if not txt or txt in seen_texts:
                continue
            seen_texts.add(txt)

            if re.match(r"^\d+\.\d{2}\.\d{2}\.", txt) or txt.startswith("[OKOZ") or txt.startswith("[TSZ") or "tahrirga qarang" in txt.lower():
                continue

            # Check article/clause headers
            m_art = article_header_regex.match(txt)
            m_clause = clause_pattern.match(txt)

            if m_art:
                flush_current_clause()
                current_clause_num = m_art.group(1)
                current_clause_title = m_art.group(2).strip()
                current_clause_type = "modda" if any(w in txt.lower() for w in ["modda", "статья"]) else "band"
            elif m_clause:
                flush_current_clause()
                current_clause_num = m_clause.group(1)
                current_clause_title = ""
                current_clause_type = "band"
                current_clause_lines.append(txt)
            elif current_clause_num:
                current_clause_lines.append(txt)

        flush_current_clause()

        return DocumentInspectionReport(
            success=True,
            url=source_url,
            law_number=law_number,
            law_title=law_title_uz,
            effective_date=date.today().isoformat(),
            total_units=len(units),
            tables_count=tables_count,
            clauses_count=clauses_count,
            units=units,
            message=f"{law_number} hujjati to'liq tahlil qilindi: {clauses_count} ta huquqiy norma va {tables_count} ta jadval AI modeliga tayyorlandi."
        )

    def _process_table(self, tbl) -> Tuple[str, str, str]:
        """Converts HTML table to clean Markdown and structured semantic key-value lines."""
        rows = []
        for tr in tbl.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                rows.append(cells)
        if not rows or len(rows) < 2:
            return "", "", ""

        headers = rows[0]
        # Clean headers
        headers = [cyrillic_to_latin(h) if detect_script(h) == "cyrillic" else normalize_apostrophes(h) for h in headers]

        md_lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
        semantic_lines = []

        for r in rows[1:]:
            r_clean = [cyrillic_to_latin(c) if detect_script(c) == "cyrillic" else normalize_apostrophes(c) for c in r]
            padded = r_clean + [""] * max(0, len(headers) - len(r_clean))
            md_lines.append("| " + " | ".join(padded[:len(headers)]) + " |")

            pairs = [f"{h}: {val}" for h, val in zip(headers, padded) if val]
            if pairs:
                semantic_lines.append(" • " + "; ".join(pairs))

        md_table = "\n".join(md_lines)
        semantic_text = "\n".join(semantic_lines)

        # Simple HTML preview
        html_preview = f"<div class='overflow-x-auto my-2'><table class='min-w-full divide-y divide-slate-200 border text-xs'>"
        html_preview += f"<thead class='bg-slate-50'><tr>" + "".join(f"<th class='px-3 py-2 text-left font-semibold text-slate-700'>{h}</th>" for h in headers) + "</tr></thead>"
        html_preview += f"<tbody class='divide-y divide-slate-100 bg-white'>"
        for r in rows[1:6]:
            html_preview += "<tr>" + "".join(f"<td class='px-3 py-2 text-slate-600'>{c}</td>" for c in r[:len(headers)]) + "</tr>"
        if len(rows) > 6:
            html_preview += f"<tr><td colspan='{len(headers)}' class='px-3 py-1.5 text-center text-slate-400 italic font-mono'>... yana {len(rows)-6} ta qator mavjud ...</td></tr>"
        html_preview += "</tbody></table></div>"

        return md_table, semantic_text, html_preview

    def _detect_category(self, text: str, law_title: str = "") -> str:
        title_low = law_title.lower()
        if any(w in title_low for w in ["transport", "транспорт", "chipta", "чипта", "yo'lovchi", "yo'l haqi"]):
            return "transport_benefits"
        if any(w in title_low for w in ["mehnat", "меҳнат", "ish o'rni", "bandlik", "бандлик", "kvota", "квота"]):
            return "labor_rights"
        if any(w in title_low for w in ["soliq", "солиқ", "boj", "бож", "imtiyoz"]):
            return "tax_benefits"
        if any(w in title_low for w in ["tmek", "тмек", "tiek", "тиек", "tibbiy-ijtimoiy", "ekspertiza"]):
            return "medical_social_expertise"
        if any(w in title_low for w in ["protez", "протез", "reabilitatsiya", "аравача", "aravacha"]):
            return "rehabilitation_prosthetics"
        if any(w in title_low for w in ["sanatoriy", "санаторий", "davolanish"]):
            return "sanatorium_health"
        if any(w in title_low for w in ["inklyuziv", "инклюзив", "ta'lim"]):
            return "inclusive_education"
        if any(w in title_low for w in ["to'siqsiz", "тўсиқсиз", "pandus"]):
            return "accessibility_infrastructure"
        if any(w in title_low for w in ["pensiya", "пенсия", "nafaqa", "нафақа"]):
            return "pensions_and_benefits"

        text_low = text.lower()
        if any(w in text_low for w in ["tmek", "тмек", "tiek", "тиек", "tibbiy-ijtimoiy", "тиббий-ижтимоий"]):
            return "medical_social_expertise"
        if any(w in text_low for w in ["transport", "транспорт", "chipta", "чипта", "avtobus", "poezd", "yo'l haqi"]):
            return "transport_benefits"
        if any(w in text_low for w in ["mehnat", "меҳнат", "ish o'rni", "bandlik", "бандлик", "kvota", "квота"]):
            return "labor_rights"
        if any(w in text_low for w in ["soliq", "солиқ", "imtiyoz", "имтиёз"]):
            return "tax_benefits"
        if any(w in text_low for w in ["pensiya", "пенсия", "nafaqa", "нафақа", "kompensatsiya", "компенсация"]):
            return "pensions_and_benefits"
        if any(w in text_low for w in ["protez", "протез", "reabilitatsiya", "реабилитация", "aravacha", "аравача"]):
            return "rehabilitation_prosthetics"
        if any(w in text_low for w in ["sanatoriy", "санаторий", "davolanish", "йўлланма", "yo'llanma"]):
            return "sanatorium_health"
        if any(w in text_low for w in ["inklyuziv", "инклюзив", "ta'lim", "таълим", "maktab", "мактаб"]):
            return "inclusive_education"
        if any(w in text_low for w in ["to'siqsiz", "тўсиқсиз", "pandus", "пандус", "shaharsozlik", "шаҳарсозlik", "infratuzilma"]):
            return "accessibility_infrastructure"
        return "disability_rights"

    def _detect_clause_topic(self, text: str, parent_category: str) -> Tuple[str, str]:
        """Detects the specific subtopic of an individual clause (e.g. court appeal, benefits, quota, enactment)."""
        text_low = text.lower()

        # 1. Enactment, procedural or formal clause
        if any(w in text_low for w in [
            "tasdiqlansin", "тасдиқлансин", "kuchga kiradi", "кучга киради",
            "kuchga kiritilsin", "ijrosi yuklansin", "nazorati yuklansin",
            "o'z kuchini yo'qotgan", "ўз кучини йўқотган", "ilova tasdiqlansin",
            "quyidagilar tasdiqlansin", "tashkiliy chora"
        ]):
            return "organizational_enactment", "Tashkiliy-tasdiqlovchi qoidalar (Nizom va ro'yxatlarni tasdiqlash)"

        # 2. Specific substantive topics
        if any(w in text_low for w in ["sudga", "судга", "sud", "суд", "norozi", "норози", "shikoyat", "шикоят", "da'vo", "низо", "nizo"]):
            return "court_appeal", "Sud himoyasi va qarorlar ustidan shikoyat qilish tartibi"
        if any(w in text_low for w in ["transport", "транспорт", "chipta", "чипта", "avtobus", "метро", "poyezd", "yo'l haqi", "yo'lovchi", "chiptasiz"]):
            return "transport_benefits", "Transportdan imtiyozli foydalanish va bepul yurish huquqi"
        if any(w in text_low for w in ["pensiya", "пенсия", "nafaqa", "нафақа", "kompensatsiya", "компенсация", "bir martalik", "to'lov"]):
            return "pensions_and_benefits", "Pensiya, nafaqa va moddiy to'lovlar"
        if any(w in text_low for w in ["mehnat", "меҳнат", "ish o'rni", "ishga qabul", "bo'shatish", "ta'til", "kvota", "ish vaqti"]):
            return "labor_rights", "Mehnat huquqlari va ish o'rinlari kafolati"
        if any(w in text_low for w in ["tmek", "тмек", "tiek", "тиек", "komissiya", "комиссия", "ko'rik", "кўрик", "tibbiy", "тиббий", "ekspertiza"]):
            return "medical_social_expertise", "Tibbiy-ijtimoiy ekspertiza (TMEK) va nogironlikni belgilash"
        if any(w in text_low for w in ["soliq", "солиқ", "boj", "бож", "imtiyoz", "имтиёз"]):
            return "tax_benefits", "Soliq va davlat boji imtiyozlari"
        if any(w in text_low for w in ["protez", "протез", "reabilitatsiya", "аравача", "aravacha", "eshitish apparat"]):
            return "rehabilitation_prosthetics", "Protez-ortopediya va reabilitatsiya ta'minoti"
        if any(w in text_low for w in ["sanatoriy", "санаторий", "davolanish", "yo'llanma"]):
            return "sanatorium_health", "Sanatoriy-kurortda bepul davolanish"
        if any(w in text_low for w in ["inklyuziv", "инклюзив", "ta'lim", "таълим"]):
            return "inclusive_education", "Inklyuziv ta'lim va grant kvotalari"

        parent_name = CATEGORY_NAMES_UZ.get(parent_category, parent_category)
        return parent_category, parent_name

    def _detect_disability_types(self, text: str) -> List[str]:
        types = set()
        text_low = text.lower()
        if "1-guruh" in text_low or "i guruh" in text_low or "i гуруҳ" in text_low:
            types.add("group_1")
        if "2-guruh" in text_low or "ii guruh" in text_low or "ii гуруҳ" in text_low:
            types.add("group_2")
        if "3-guruh" in text_low or "iii guruh" in text_low or "iii гуруҳ" in text_low:
            types.add("group_3")
        if "bola" in text_low or "бола" in text_low:
            types.add("childhood_disability")
        if "ko'rish" in text_low or "кўриш" in text_low or "ko'zi ojiz" in text_low:
            types.add("visual")
        if "eshitish" in text_low or "эшитиш" in text_low or "kar" in text_low:
            types.add("hearing")
        if "harakat" in text_low or "ҳаракат" in text_low or "tayanch" in text_low:
            types.add("physical")
        if not types:
            types.add("general")
        return sorted(list(types))

    def to_canonical_articles(self, report: DocumentInspectionReport):
        """Converts inspected units (clauses and complex tables) directly into CanonicalArticles
        with exact BGE-M3 prompt embeddings guaranteed."""
        from src.schema.canonical import (
            CanonicalArticle,
            ArticleMetadata,
            ArticlePoint,
            ArticleStatus,
            TranslationProvenanceType,
        )
        law_slug = re.sub(r"[^a-z0-9_]", "_", report.law_number.lower()).strip("_")
        today = date.today().isoformat()
        articles = []

        for unit in report.units:
            cid = f"{law_slug}_{unit.unit_id}"
            hasher = hashlib.sha256()
            hasher.update(unit.exact_bge_prompt.encode("utf-8"))
            s_hash = f"sha256:{hasher.hexdigest()[:16]}"

            art = CanonicalArticle(
                canonical_id=cid,
                schema_version="1.1",
                metadata=ArticleMetadata(
                    law_id=law_slug,
                    law_title=localized(report.law_title, report.law_title),
                    law_number=report.law_number,
                    chapter_number="",
                    article_number=unit.unit_num or unit.title,
                    article_title=localized(unit.title, unit.title),
                    source_url=report.url,
                    effective_date=today,
                    last_verified_date=today,
                    source_hash=s_hash,
                    status=ArticleStatus.ACTIVE,
                    category=unit.category,
                    disability_types=unit.disability_types,
                    beneficiary_type=["person_with_disability", "individual"],
                    cross_references=[],
                    embedding_model_version="baai/bge-m3",
                ),
                points=[ArticlePoint(point_id="1", text=localized(unit.exact_bge_prompt, unit.exact_bge_prompt))],
                translations=localized(unit.exact_bge_prompt, unit.exact_bge_prompt),
                translation_provenance=provenance_for(localized(unit.exact_bge_prompt, unit.exact_bge_prompt))
            )
            articles.append(art)
        return articles

