#!/usr/bin/env python3
"""
Uzbekistan Legal RAG — Stage 1 Comprehensive Ingestion Orchestrator.
Processes all official .doc exports from Lex.uz (Decrees, Resolutions, Orders,
Parliament Acts, International Treaties), parses articles/clauses,
and indexes into LanceDB + SQLite FTS5 with robust checkpointing.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.schema.canonical import (
    CanonicalArticle,
    ArticleMetadata,
    ArticlePoint,
    ArticleStatus,
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
from src.ingestion.universal_engine import DocumentSpec, UniversalParser
from scripts.ingest_all_laws import parse_act_list_doc, check_document_active_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/store/stage1_ingest.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

CATEGORY_MAP = {
    "farmonlar": {
        "file": "data/qonunlar/farmonlar_act_list.doc",
        "category": "decrees",
        "prefix": "farmon",
        "name": "Prezident Farmonlari",
    },
    "buyruqlar": {
        "file": "data/qonunlar/Buyruq.doc",
        "category": "departmental",
        "prefix": "buyruq",
        "name": "Vazirlik va idoralar buyruqlari",
    },
    "oliy_majlis": {
        "file": "data/qonunlar/Oliy_majlis_qaror.doc",
        "category": "parliament_resolutions",
        "prefix": "om_qaror",
        "name": "Oliy Majlis qarorlari",
    },
    "xalqaro": {
        "file": "data/qonunlar/Xalqaro_hujjatlar.doc",
        "category": "international_treaties",
        "prefix": "xalqaro",
        "name": "Xalqaro shartnomalar va konvensiyalar",
    },
    "qarorlar": {
        "file": "data/qonunlar/qaror.doc",
        "category": "resolutions",
        "prefix": "qaror",
        "name": "Hukumat va Prezident qarorlari",
    },
    "farmoyishlar": {
        "file": "data/qonunlar/farmoyish.doc",
        "category": "directives",
        "prefix": "farmoyish",
        "name": "Farmoyishlar",
    },
    "nizomlar": {
        "file": "data/qonunlar/nizom_1.doc",
        "category": "regulations",
        "prefix": "nizom",
        "name": "Nizomlar",
    },
    "tartiblar": {
        "file": "data/qonunlar/tartib.doc",
        "category": "regulations",
        "prefix": "tartib",
        "name": "Tartiblar",
    },
    "qoraqalpogiston": {
        "file": "data/qonunlar/qoraqalpogiston_respublikasi_konstitutsiyasi.doc",
        "category": "constitution",
        "prefix": "qr_konstitutsiya",
        "name": "Qoraqalpog'iston Respublikasi Konstitutsiyasi",
    },
}


def build_slug(prefix: str, doc_number: str, doc_id: str) -> str:
    """Builds a clean, deterministic Latin slug."""
    clean_num = re.sub(r"[^a-zA-Z0-9]+", "_", doc_number).strip("_").lower()
    # Transliterate Cyrillic characters in number (e.g. ПФ -> pf, ВМҚ -> vmq)
    clean_num = cyrillic_to_latin(clean_num)
    clean_num = re.sub(r"[^a-zA-Z0-9]+", "_", clean_num).strip("_")
    if clean_num:
        return f"{prefix}_{clean_num}"
    return f"{prefix}_doc_{doc_id}"


async def ingest_single_document(
    http_client: httpx.AsyncClient,
    store: HybridStore,
    openrouter_client: OpenRouterClient,
    item: Dict,
    cat_config: Dict,
    catalog_dir: Path,
    batch_size: int = 30,
) -> Dict:
    """Ingests a single normative document into the hybrid store."""
    doc_id = item["doc_id"]
    raw_num = item.get("law_number", "")
    title = item.get("title", "")
    eff_date = item.get("effective_date", "2020-01-01")
    prefix = cat_config["prefix"]
    category = cat_config["category"]

    slug = build_slug(prefix, raw_num, doc_id)
    url = f"https://lex.uz/docs/{doc_id}"
    cache_path = catalog_dir / f"{slug}.json"

    # Fast cache & store check
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data and store.get_article(data[0].get("canonical_id")):
                return {"slug": slug, "status": "already_indexed", "articles": len(data)}
        except Exception:
            pass

    # 1. Fetch Lex.uz HTML
    try:
        resp = await http_client.get(url)
        if resp.status_code != 200:
            return {"slug": slug, "status": "failed_fetch", "error": f"HTTP {resp.status_code}"}
        html_uz = resp.text
    except Exception as e:
        return {"slug": slug, "status": "failed_fetch", "error": str(e)}

    # 2. Check for PDF-only document (e.g. freshly published)
    if "pdfBody" in html_uz and "divCont" not in html_uz:
        return {"slug": slug, "status": "skipped_pdf_only", "reason": "HTML text pending (PDF only on Lex.uz)"}

    # 3. Check active status
    soup = BeautifulSoup(html_uz[:12000], "html.parser")
    is_active, status_reason = check_document_active_status(soup)
    if not is_active:
        return {"slug": slug, "status": "skipped_repealed", "reason": status_reason}

    # 3b. Extract official language URLs from Lex.uz page header (На русском, In english, O'zbekcha)
    full_soup = BeautifulSoup(html_uz, "html.parser")
    lang_links = UniversalParser.extract_lex_language_links(full_soup)

    html_ru = None
    if "ru" in lang_links:
        try:
            resp_ru = await http_client.get(lang_links["ru"])
            if resp_ru.status_code == 200:
                html_ru = resp_ru.text
        except Exception as e:
            logger.debug(f"Could not fetch official RU from {lang_links['ru']}: {e}")

    # 4. Parse using UniversalParser (tries statutory articles first, then regulation clauses)
    spec = DocumentSpec(
        slug=slug,
        category=category,
        doc_number=raw_num or f"Hujjat #{doc_id}",
        title_uz=title,
        effective_date=eff_date[:10] if eff_date else "2020-01-01",
        url_uz=url,
        parser_type="regulation_clause" if category in ["decrees", "resolutions", "departmental", "directives"] else "statutory_article",
    )

    articles = UniversalParser.parse_statutory_articles(html_uz, spec, html_ru)
    if not articles:
        articles = UniversalParser.parse_regulation_clauses(html_uz, spec, html_ru)

    # Fallback if document has single operative text without standard numbering
    if not articles:
        div = full_soup.find(id="divCont") or full_soup.find(class_="docBody") or full_soup.find("body")
        if div:
            clean_div = UniversalParser.clean_soup(div)
            text = UniversalParser.clean_text(clean_div.get_text())
            if len(text) > 100:
                is_cyrillic = detect_script(text) == "cyrillic"
                is_russian = is_cyrillic and is_genuine_russian(text)
                text_uz = cyrillic_to_latin(text) if (is_cyrillic and not is_russian) else normalize_apostrophes(text)
                text_uz_cyrl = text if (is_cyrillic and not is_russian) else ""
                text_ru = text if is_russian else ""

                if html_ru:
                    soup_ru = UniversalParser.clean_soup(BeautifulSoup(html_ru, "html.parser"))
                    div_ru = soup_ru.find(id="divCont") or soup_ru.find(class_="docBody")
                    if div_ru:
                        clean_ru = UniversalParser.clean_text(div_ru.get_text())
                        if len(clean_ru) > 100:
                            text_ru = clean_ru
                
                hasher = hashlib.sha256()
                hasher.update(text_uz.encode("utf-8"))

                translations = {"uz": text_uz, "ru": text_ru, "en": ""}
                if text_uz_cyrl:
                    translations["uz_cyrl"] = text_uz_cyrl

                pt_dict = {"uz": text_uz, "ru": text_ru, "en": ""}
                if text_uz_cyrl:
                    pt_dict["uz_cyrl"] = text_uz_cyrl

                prov = {
                    "uz": TranslationProvenanceType.OFFICIAL,
                    "ru": TranslationProvenanceType.OFFICIAL if text_ru else TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                    "en": TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                }
                if text_uz_cyrl:
                    prov["uz_cyrl"] = TranslationProvenanceType.OFFICIAL

                law_title_dict = {
                    "uz": title,
                    "ru": title if (is_genuine_russian(title)) else "",
                    "en": title,
                }
                if text_uz_cyrl and detect_script(title) == "cyrillic":
                    law_title_dict["uz_cyrl"] = title

                meta = ArticleMetadata(
                    law_id=slug,
                    law_title=law_title_dict,
                    law_number=spec.doc_number,
                    chapter_number=None,
                    article_number="1-matn",
                    article_title={"uz": title[:80], "ru": title[:80] if text_ru else "", "en": title[:80]},
                    source_url=url,
                    effective_date=spec.effective_date,
                    last_verified_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    source_hash=f"sha256:{hasher.hexdigest()}",
                    status=ArticleStatus.ACTIVE,
                    category=category,
                    disability_types=["general"],
                    beneficiary_type=["citizen", "legal_entity", "state_body"],
                    cross_references=[],
                    embedding_model_version="bge-m3-2025-11-18",
                )
                articles.append(CanonicalArticle(
                    canonical_id=f"{slug}_art_1",
                    schema_version="1.1",
                    metadata=meta,
                    points=[ArticlePoint(point_id="1", text=pt_dict)],
                    translations=translations,
                    translation_provenance=prov,
                ))

    if not articles:
        return {"slug": slug, "status": "empty_content", "articles": 0}

    # 5. Save canonical JSON cache
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump([a.model_dump() for a in articles], f, ensure_ascii=False, indent=2)

    # 6. Index into LanceDB and SQLite FTS5 using batch indexing
    indexed = await store.index_articles_batch(articles, client=openrouter_client, batch_size=batch_size)

    return {"slug": slug, "status": "success", "articles": indexed}


async def process_category(
    cat_key: str,
    cat_config: Dict,
    store: HybridStore,
    openrouter_client: OpenRouterClient,
    http_client: httpx.AsyncClient,
    limit: int = 0,
    delay: float = 0.35,
    batch_size: int = 30,
) -> Dict:
    """Processes a single category file end-to-end."""
    doc_file = Path(cat_config["file"])
    if not doc_file.exists():
        logger.error(f"Category file not found: {doc_file}")
        return {"error": f"File not found: {doc_file}"}

    items = parse_act_list_doc(doc_file)
    logger.info(f"📂 Category '{cat_config['name']}' ({cat_key}): loaded {len(items)} items from {doc_file}")

    if limit > 0:
        items = items[:limit]
        logger.info(f"⚡ Limited to first {len(items)} items for {cat_key}")

    catalog_dir = Path("data/laws_catalog") / cat_key
    catalog_dir.mkdir(parents=True, exist_ok=True)

    progress_file = Path("data/laws_catalog") / f"{cat_key}_progress.json"
    stats = {
        "category": cat_key,
        "name": cat_config["name"],
        "total": len(items),
        "success": 0,
        "already_indexed": 0,
        "skipped_repealed": 0,
        "skipped_pdf_only": 0,
        "errors": 0,
        "articles": 0,
    }

    start_time = time.time()
    for idx, item in enumerate(items, 1):
        num = item.get("law_number", f"ID {item['doc_id']}")
        try:
            res = await ingest_single_document(
                http_client=http_client,
                store=store,
                openrouter_client=openrouter_client,
                item=item,
                cat_config=cat_config,
                catalog_dir=catalog_dir,
                batch_size=batch_size,
            )
            st = res.get("status", "unknown")
            arts = res.get("articles", 0)

            if st == "success":
                stats["success"] += 1
                stats["articles"] += arts
                logger.info(f"[{idx}/{len(items)}] SUCCESS {num}: {arts} articles/clauses indexed.")
            elif st == "already_indexed":
                stats["already_indexed"] += 1
                logger.info(f"[{idx}/{len(items)}] SKIP_ALREADY_INDEXED {num}")
            elif st == "skipped_repealed":
                stats["skipped_repealed"] += 1
                logger.info(f"[{idx}/{len(items)}] SKIP_REPEALED {num}")
            elif st == "skipped_pdf_only":
                stats["skipped_pdf_only"] += 1
                logger.info(f"[{idx}/{len(items)}] SKIP_PDF_ONLY {num}")
            else:
                stats["errors"] += 1
                logger.warning(f"[{idx}/{len(items)}] {st} {num}: {res.get('error', '')}")

        except Exception as e:
            stats["errors"] += 1
            logger.error(f"[{idx}/{len(items)}] EXCEPTION {num}: {e}", exc_info=False)

        # Periodic checkpoint
        if idx % 15 == 0 or idx == len(items):
            elapsed = time.time() - start_time
            stats["elapsed_seconds"] = round(elapsed, 1)
            stats["store_total"] = store.count()
            with open(progress_file, "w", encoding="utf-8") as pf:
                json.dump(stats, pf, ensure_ascii=False, indent=2)
            logger.info(
                f"📊 [{cat_key.upper()} Progress {idx}/{len(items)}] Success: {stats['success']} | "
                f"Articles: {stats['articles']} | Store Count: {store.count():,} | Elapsed: {elapsed:.1f}s"
            )
        if st not in ["already_indexed"]:
            await asyncio.sleep(delay)

    return stats


async def main():
    parser = argparse.ArgumentParser(description="Stage 1 Legal RAG Ingestion Orchestrator")
    parser.add_argument("--category", type=str, default="all", choices=list(CATEGORY_MAP.keys()) + ["all"],
                        help="Category to process (default: all)")
    parser.add_argument("--limit", type=int, default=0, help="Limit items per category (0 = all)")
    parser.add_argument("--delay", type=float, default=0.35, help="Delay between document fetches in seconds (default: 0.35)")
    parser.add_argument("--batch-size", type=int, default=30, help="Embedding batch size (default: 30)")
    args = parser.parse_args()

    store = HybridStore()
    openrouter_client = OpenRouterClient()
    logger.info("=" * 65)
    logger.info("🚀 UZBEKISTAN LEGAL RAG — STAGE 1 COMPREHENSIVE INGESTION")
    logger.info(f"🏛️ Initial store count: {store.count():,} articles/clauses")
    logger.info("=" * 65)

    headers = {
        "User-Agent": "UzbekistanLegalRAG/1.0 (Government & Citizen Legal Access Research; contact@legal-rag.uz)",
        "Accept-Language": "uz,ru;q=0.9",
    }

    categories_to_run = (
        ["farmonlar", "buyruqlar", "oliy_majlis", "xalqaro", "qarorlar", "farmoyishlar", "nizomlar", "tartiblar", "qoraqalpogiston"]
        if args.category == "all"
        else [args.category]
    )

    async with httpx.AsyncClient(timeout=40.0, follow_redirects=True, headers=headers) as http_client:
        for cat_key in categories_to_run:
            cfg = CATEGORY_MAP[cat_key]
            logger.info(f"\n▶️ STARTING CATEGORY: {cfg['name']} ({cat_key})...")
            cat_stats = await process_category(
                cat_key=cat_key,
                cat_config=cfg,
                store=store,
                openrouter_client=openrouter_client,
                http_client=http_client,
                limit=args.limit,
                delay=args.delay,
                batch_size=args.batch_size,
            )
            logger.info(f"✅ FINISHED CATEGORY: {cfg['name']} -> {cat_stats}")

    logger.info("=" * 65)
    logger.info(f"🏁 STAGE 1 INGESTION COMPLETE. Final Store Count: {store.count():,} articles/clauses.")
    logger.info("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
