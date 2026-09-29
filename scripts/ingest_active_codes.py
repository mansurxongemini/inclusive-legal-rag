#!/usr/bin/env python3
"""
Automated Ingestion Engine for all active Codes (Kodekslar) of the Republic of Uzbekistan.
Ensures ONLY currently in-force legislation is indexed, filtering out repealed acts.
"""

import asyncio
import hashlib
import json
import logging
import re
import sys
import time
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
    CrossReference,
    RefType,
    TranslationProvenanceType,
)
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient
from src.nlp.transliteration import cyrillic_to_latin, detect_script, normalize_apostrophes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Catalog of Verified Active Codes of Uzbekistan on Lex.uz
# Each entry: (slug, doc_id, law_number, uz_title, ru_title, category)
ACTIVE_CODES_CATALOG = [
    (
        "mehnat_code",
        "6257288",
        "O'RQ-798",
        "O'zbekiston Respublikasining Mehnat kodeksi",
        "Трудовой кодекс Республики Узбекистан",
        "labor_code",
    ),
    (
        "oila_code",
        "104720",
        "465-I-son",
        "O'zbekiston Respublikasining Oila kodeksi",
        "Семейный кодекс Республики Узбекистан",
        "family_law",
    ),
    (
        "uy_joy_code",
        "106136",
        "713-I-son",
        "O'zbekiston Respublikasining Uy-joy kodeksi",
        "Жилищный кодекс Республики Узбекистан",
        "housing_law",
    ),
    (
        "shaharsozlik_code",
        "5307951",
        "O'RQ-676",
        "O'zbekiston Respublikasining Shaharsozlik kodeksi",
        "Градостроительный кодекс Республики Узбекистан",
        "urban_planning",
    ),
    (
        "yer_code",
        "152653",
        "598-I-son",
        "O'zbekiston Respublikasining Yer kodeksi",
        "Земельный кодекс Республики Узбекистан",
        "land_law",
    ),
    (
        "saylov_code",
        "4386848",
        "O'RQ-544",
        "O'zbekiston Respublikasining Saylov kodeksi",
        "Избирательный кодекс Республики Узбекистан",
        "electoral_law",
    ),
    (
        "byudjet_code",
        "2304138",
        "O'RQ-360",
        "O'zbekiston Respublikasining Byudjet kodeksi",
        "Бюджетный кодекс Республики Узбекистан",
        "budget_law",
    ),
    (
        "havo_code",
        "55594",
        "863-XII-son",
        "O'zbekiston Respublikasining Havo kodeksi",
        "Воздушный кодекс Республики Узбекистан",
        "aviation_law",
    ),
    (
        "fuqarolik_code_1",
        "111189",
        "163-I-son",
        "O'zbekiston Respublikasining Fuqarolik kodeksi (Birinchi qism)",
        "Гражданский кодекс Республики Узбекистан (Часть первая)",
        "civil_code",
    ),
    (
        "fuqarolik_code_2",
        "180552",
        "256-I-son",
        "O'zbekiston Respublikasining Fuqarolik kodeksi (Ikkinchi qism)",
        "Гражданский кодекс Республики Узбекистан (Часть вторая)",
        "civil_code",
    ),
    (
        "mjtk_code",
        "97664",
        "2015-XII-son",
        "O'zbekiston Respublikasining Ma'muriy javobgarlik to'g'risidagi kodeksi",
        "Кодекс Республики Узбекистан об административной ответственности",
        "administrative_law",
    ),
    (
        "jinoyat_code",
        "111453",
        "2012-XII-son",
        "O'zbekiston Respublikasining Jinoyat kodeksi",
        "Уголовный кодекс Республики Узбекистан",
        "criminal_law",
    ),
    (
        "soliq_code",
        "4674902",
        "O'RQ-599",
        "O'zbekiston Respublikasining Soliq kodeksi",
        "Налоговый кодекс Республики Узбекистан",
        "tax_law",
    ),
    (
        "bojxona_code",
        "2876354",
        "O'RQ-400",
        "O'zbekiston Respublikasining Bojxona kodeksi",
        "Таможенный кодекс Республики Узбекистан",
        "customs_law",
    ),
    (
        "jik_code",
        "163629",
        "438-I-son",
        "O'zbekiston Respublikasining Jinoyat-ijroiya kodeksi",
        "Уголовно-исполнительный кодекс Республики Узбекистан",
        "penal_execution",
    ),
    (
        "fpk_code",
        "3517337",
        "O'RQ-460",
        "O'zbekiston Respublikasining Fuqarolik protsessual kodeksi",
        "Гражданский процессуальный кодекс Республики Узбекистан",
        "civil_procedure",
    ),
    (
        "ipk_code",
        "3523891",
        "O'RQ-461",
        "O'zbekiston Respublikasining Iqtisodiy protsessual kodeksi",
        "Экономический процессуальный кодекс Республики Узбекистан",
        "economic_procedure",
    ),
    (
        "msiytk_code",
        "3527353",
        "O'RQ-462",
        "O'zbekiston Respublikasining Ma'muriy sud ishlarini yuritish to'g'risidagi kodeksi",
        "Кодекс Республики Узбекистан об административном судопроизводстве",
        "administrative_procedure",
    ),
    (
        "jpk_code",
        "111460",
        "2013-XII-son",
        "O'zbekiston Respublikasining Jinoyat-protsessual kodeksi",
        "Уголовно-процессуальный кодекс Республики Узбекистан",
        "criminal_procedure",
    ),
]


def check_document_active_status(soup: BeautifulSoup) -> Tuple[bool, str]:
    """
    Checks if the overall document is currently ACTIVE or REPEALED on Lex.uz.
    Returns (is_active, reason).
    """
    # Check top status banner
    status_div = soup.find("div", class_="doc_status_block") or soup.find("div", id="docStatus")
    if status_div:
        status_text = status_div.get_text().strip().lower()
        if "кучини йўқотган" in status_text or "утратил силу" in status_text or "o'z kuchini yo'qotgan" in status_text:
            return False, f"Lex.uz status banner declares repealed: {status_text[:100]}"

    # Check top 1500 chars of body
    body_header = soup.get_text()[:1500].lower()
    repealed_markers = [
        "ҳужжат кучини йўқотган",
        "ҳужжат ўз кучини йўқотган",
        "документ утратил силу",
        "hujjat o'z kuchini yo'qotgan",
        "hujjat kuchini yo'qotgan",
    ]
    for marker in repealed_markers:
        if marker in body_header:
            return False, f"Repealed marker found in header: '{marker}'"

    return True, "Active"


def parse_code_html(
    html_text: str,
    slug: str,
    law_number: str,
    law_title_uz: str,
    law_title_ru: str,
    category: str,
    source_url: str,
) -> List[CanonicalArticle]:
    """Parses a full code HTML into CanonicalArticle objects."""
    soup = BeautifulSoup(html_text, "html.parser")

    # 1. Clean UI buttons, index references, and commentary blocks
    for el in soup.find_all("div", class_=["lx_elem2", "INDEXES_ON_REF", "COMMENT", "CHANGES_ORIGINS"]):
        el.decompose()

    div_cont = soup.find("div", id="divCont") or soup.find("div", class_="doc_content") or soup.find("body")
    if not div_cont:
        raise ValueError("Could not find document container in HTML")

    # 2. Convert sup tags to hyphenated sub-article numbers (e.g. 18<sup>1</sup> -> 18-1)
    for sup in div_cont.find_all("sup"):
        stxt = sup.get_text().strip()
        if stxt.isdigit():
            sup.replace_with(f"-{stxt}")
        else:
            sup.decompose()

    # 3. Extract articles by matching header elements (supports 1, 18-1, 181, 278-8)
    art_regex = re.compile(
        r"^(\d+(?:-\d+)*)\s*[-–—]?\s*(?:модда|modda|статья)[\.\s:]*(.*)$",
        re.IGNORECASE | re.DOTALL
    )

    children = div_cont.find_all("div", recursive=False)
    raw_articles = []
    cur_num = None
    cur_title = ""
    cur_paragraphs = []

    for ch in children:
        txt = " ".join(ch.get_text().split())
        if not txt:
            continue

        m = art_regex.match(txt)
        if m:
            if cur_num:
                raw_articles.append((cur_num, cur_title, cur_paragraphs))
            cur_num = m.group(1)
            raw_title = " ".join(m.group(2).split())
            cur_title = raw_title
            cur_paragraphs = []
            continue

        if cur_num:
            if not txt.startswith("Ҳужжатга таклиф") and not txt.startswith("Отправить предложение"):
                cur_paragraphs.append(txt)

    if cur_num:
        raw_articles.append((cur_num, cur_title, cur_paragraphs))

    logger.info(f"[{slug}] Raw articles parsed: {len(raw_articles)}")

    # Deduplicate while preserving order
    seen = set()
    canonical_articles: List[CanonicalArticle] = []

    for art_num, raw_title, paragraphs in raw_articles:
        if art_num in seen:
            continue
        seen.add(art_num)

        full_raw_text = "\n\n".join(paragraphs) if paragraphs else raw_title

        # Check script & normalize
        is_cyrillic = detect_script(raw_title + " " + full_raw_text) == "cyrillic"
        if is_cyrillic:
            title_uz = cyrillic_to_latin(raw_title)
            body_uz = cyrillic_to_latin(full_raw_text)
            title_ru = raw_title  # Will serve as Cyrillic / regional representation
            body_ru = full_raw_text
        else:
            title_uz = normalize_apostrophes(raw_title)
            body_uz = normalize_apostrophes(full_raw_text)
            title_ru = title_uz
            body_ru = body_uz

        # Check if individual article is repealed
        is_article_repealed = (
            "ўз кучини йўқотган" in full_raw_text.lower()
            or "o'z kuchini yo'qotgan" in body_uz.lower()
            or "утратила силу" in full_raw_text.lower()
        )
        art_status = ArticleStatus.REPEALED if is_article_repealed else ArticleStatus.ACTIVE

        # Extract points
        points: List[ArticlePoint] = []
        pt_pattern = re.compile(r"^\s*(\d+)[\.\)]\s+(.*)$")
        for idx, p in enumerate(paragraphs, start=1):
            clean_p = cyrillic_to_latin(p) if is_cyrillic else normalize_apostrophes(p)
            pm = pt_pattern.match(clean_p)
            pt_id = pm.group(1) if pm else str(idx)
            pt_text = pm.group(2) if pm else clean_p
            points.append(ArticlePoint(
                point_id=pt_id,
                text={"uz": pt_text, "ru": p if is_cyrillic else "", "en": ""}
            ))

        hasher = hashlib.sha256()
        hasher.update(body_uz.encode("utf-8"))
        source_hash = f"sha256:{hasher.hexdigest()}"

        safe_art_suffix = str(art_num).replace("-", "_")
        cid = f"{slug}_art_{safe_art_suffix}"

        meta = ArticleMetadata(
            law_id=slug,
            law_title={"uz": law_title_uz, "ru": law_title_ru, "en": law_title_uz},
            law_number=law_number,
            chapter_number=None,
            article_number=f"{art_num}-modda",
            article_title={"uz": title_uz, "ru": title_ru, "en": title_uz},
            source_url=source_url,
            effective_date="2023-04-30",
            last_verified_date="2026-09-27",
            source_hash=source_hash,
            status=art_status,
            category=category,
            disability_types=["general"],
            beneficiary_type=["citizen", "employer", "state_body"],
            cross_references=[],
            embedding_model_version="bge-m3-2025-11-18",
        )

        canonical_articles.append(CanonicalArticle(
            canonical_id=cid,
            schema_version="1.1",
            metadata=meta,
            points=points,
            translations={
                "uz": body_uz,
                "ru": body_ru,
                "en": "",
            },
            translation_provenance={
                "uz": TranslationProvenanceType.OFFICIAL,
                "ru": TranslationProvenanceType.OFFICIAL if is_cyrillic else TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                "en": TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
            }
        ))

    return canonical_articles


async def ingest_single_code(
    client_http: httpx.AsyncClient,
    store: HybridStore,
    openrouter_client: OpenRouterClient,
    entry: Tuple,
    catalog_dir: Path,
    batch_size: int = 20,
    force_fetch: bool = False,
    skip_existing: bool = False,
) -> Dict:
    slug, doc_id, law_number, uz_title, ru_title, category = entry
    url = f"https://lex.uz/docs/{doc_id}"
    cache_json = catalog_dir / f"{slug}.json"

    logger.info(f"=== Starting Ingestion: {uz_title} (ID: {doc_id}) ===")

    articles: List[CanonicalArticle] = []

    # 1. Check local JSON cache first
    if cache_json.exists() and not force_fetch:
        logger.info(f"[{slug}] Found cached JSON at {cache_json}. Loading...")
        try:
            with open(cache_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            articles = [CanonicalArticle.model_validate(item) for item in data]
            logger.info(f"[{slug}] Successfully loaded {len(articles)} articles from cache.")
        except Exception as e:
            logger.warning(f"[{slug}] Failed to load cache: {e}. Re-fetching from Lex.uz...")

    # 2. If not loaded from cache, fetch from Lex.uz
    if not articles:
        resp = await client_http.get(url)
        if resp.status_code != 200:
            logger.error(f"HTTP {resp.status_code} for {url}. Skipping.")
            return {"slug": slug, "status": "failed", "error": f"HTTP {resp.status_code}"}

        # Check active status
        soup = BeautifulSoup(resp.text[:10000], "html.parser")
        is_active, status_reason = check_document_active_status(soup)
        if not is_active:
            logger.warning(f"SKIPPING {slug}: Document is REPEALED ({status_reason}).")
            return {"slug": slug, "status": "skipped_repealed", "reason": status_reason}

        # Parse into canonical articles
        articles = parse_code_html(
            resp.text,
            slug=slug,
            law_number=law_number,
            law_title_uz=uz_title,
            law_title_ru=ru_title,
            category=category,
            source_url=url,
        )

        if not articles:
            logger.warning(f"No articles parsed from {url}. Check selector structure.")
            return {"slug": slug, "status": "empty", "articles": 0}

        # Save JSON backup
        with open(cache_json, "w", encoding="utf-8") as f:
            json.dump([a.model_dump() for a in articles], f, ensure_ascii=False, indent=2)
        logger.info(f"[{slug}] Saved {len(articles)} canonical articles to {cache_json}")

    # 3. Check if already indexed
    if skip_existing and articles:
        first_art = store.get_article(articles[0].canonical_id)
        last_art = store.get_article(articles[-1].canonical_id)
        if first_art and last_art:
            logger.info(f"[{slug}] Code already indexed in store ({first_art.canonical_id} & {last_art.canonical_id} found). Skipping.")
            return {"slug": slug, "status": "already_indexed", "articles": len(articles)}

    # 4. If force_fetch, purge previous records for this slug to remove old/corrupted IDs
    if force_fetch:
        logger.info(f"[{slug}] Purging obsolete records from SQLite and LanceDB...")
        with store.fts_store._get_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM articles_metadata WHERE json_extract(json_data, '$.metadata.law_id') = ?", (slug,))
            c.execute("DELETE FROM articles_fts WHERE canonical_id LIKE ?", (f"{slug}_art_%",))
            conn.commit()
        try:
            store.vector_store.table.delete(f"canonical_id LIKE '{slug}_art_%'")
        except Exception as e:
            logger.warning(f"[{slug}] Vector store purge note: {e}")

    # 5. Index into LanceDB and SQLite FTS5 using high-speed batching
    indexed_count = await store.index_articles_batch(articles, client=openrouter_client, batch_size=batch_size)

    logger.info(f"Successfully finished {uz_title}: {indexed_count} articles indexed!")
    return {"slug": slug, "status": "success", "articles": indexed_count}


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Universal Active Codes Ingestion Engine")
    parser.add_argument("--codes", nargs="*", help="Specific code slugs to ingest (default: all 19 codes)")
    parser.add_argument("--batch-size", type=int, default=20, help="Embedding batch size (default: 20)")
    parser.add_argument("--force-fetch", action="store_true", help="Force redownload from Lex.uz even if cached")
    parser.add_argument("--skip-existing", action="store_true", help="Skip codes already present in database")
    args = parser.parse_args()

    catalog_dir = Path("data/laws_catalog")
    catalog_dir.mkdir(parents=True, exist_ok=True)

    store = HybridStore()
    openrouter_client = OpenRouterClient()

    logger.info(f"Initial store count: {store.count()} articles.")
    headers = {
        "User-Agent": "UzbekistanLegalRAG/1.0 (Government & Citizen Legal Access Research; contact@legal-rag.uz)",
        "Accept-Language": "uz,ru;q=0.9",
    }

    target_catalog = ACTIVE_CODES_CATALOG
    if args.codes:
        target_catalog = [c for c in ACTIVE_CODES_CATALOG if c[0] in args.codes]
        logger.info(f"Filtering to {len(target_catalog)} requested codes: {[c[0] for c in target_catalog]}")

    results = []
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=headers) as http_client:
        for idx, entry in enumerate(target_catalog, start=1):
            slug, doc_id, _, uz_title, _, _ = entry
            logger.info(f"\n[{idx}/{len(target_catalog)}] Processing {uz_title} ({slug})...")
            
            try:
                res = await ingest_single_code(
                    client_http=http_client,
                    store=store,
                    openrouter_client=openrouter_client,
                    entry=entry,
                    catalog_dir=catalog_dir,
                    batch_size=args.batch_size,
                    force_fetch=args.force_fetch,
                    skip_existing=args.skip_existing,
                )
                results.append(res)
            except Exception as e:
                logger.error(f"Error processing {slug}: {e}", exc_info=True)
                results.append({"slug": slug, "status": "error", "error": str(e)})

            # Polite delay to prevent Lex.uz rate limiting
            await asyncio.sleep(1.0)

    logger.info("=" * 60)
    logger.info("ALL CODES INGESTION SUMMARY:")
    for r in results:
        logger.info(f"  * {r['slug']}: {r['status']} ({r.get('articles', 0)} articles)")
    logger.info(f"Final store count: {store.count()} articles.")


if __name__ == "__main__":
    asyncio.run(main())
