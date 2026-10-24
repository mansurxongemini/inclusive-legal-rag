#!/usr/bin/env python3
"""
Enriches all 19 Codes with their official Russian translations from Lex.uz.
Updates local canonical JSON files and updates SQLite FTS5 store for bilingual search.
"""

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, Tuple
import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.schema.canonical import CanonicalArticle, TranslationProvenanceType
from src.storage.hybrid_store import HybridStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Map of slug -> (russian_doc_id, russian_law_title)
RUSSIAN_CODES_MAP = {
    "mehnat_code": ("6257291", "Трудовой кодекс Республики Узбекистан"),
    "oila_code": ("104723", "Семейный кодекс Республики Узбекистан"),
    "uy_joy_code": ("106134", "Жилищный кодекс Республики Узбекистан"),
    "shaharsozlik_code": ("5307955", "Градостроительный кодекс Республики Узбекистан"),
    "yer_code": ("149947", "Земельный кодекс Республики Узбекистан"),
    "saylov_code": ("4386846", "Избирательный кодекс Республики Узбекистан"),
    "byudjet_code": ("2304140", "Бюджетный кодекс Республики Узбекистан"),
    "havo_code": ("55599", "Воздушный кодекс Республики Узбекистан"),
    "fuqarolik_code_1": ("111181", "Гражданский кодекс Республики Узбекистан (Часть первая)"),
    "fuqarolik_code_2": ("180550", "Гражданский кодекс Республики Узбекистан (Часть вторая)"),
    "mjtk_code": ("97661", "Кодекс Республики Узбекистан об административной ответственности"),
    "jinoyat_code": ("111457", "Уголовный кодекс Республики Узбекистан"),
    "soliq_code": ("4674893", "Налоговый кодекс Республики Узбекистан"),
    "bojxona_code": ("2876352", "Таможенный кодекс Республики Узбекистан"),
    "jik_code": ("163627", "Уголовно-исполнительный кодекс Республики Узбекистан"),
    "fpk_code": ("3517334", "Гражданский процессуальный кодекс Республики Узбекистан"),
    "ipk_code": ("3523895", "Экономический процессуальный кодекс Республики Узбекистан"),
    "msiytk_code": ("3527365", "Кодекс Республики Узбекистан об административном судопроизводстве"),
    "jpk_code": ("111463", "Уголовно-процессуальный кодекс Республики Узбекистан"),
}


def parse_russian_html(html_text: str) -> Dict[str, Tuple[str, str]]:
    """
    Parses a Russian Lex.uz HTML page into a dictionary of:
    art_number -> (title, full_text)
    """
    soup = BeautifulSoup(html_text, "html.parser")
    for el in soup.find_all("div", class_=["lx_elem2", "INDEXES_ON_REF", "COMMENT", "CHANGES_ORIGINS"]):
        el.decompose()

    div_cont = soup.find("div", id="divCont") or soup.find("div", class_="doc_content") or soup.find("body")
    if not div_cont:
        return {}

    # Convert sup tags to hyphenated numbers (e.g. 18<sup>1</sup> -> 18-1)
    for sup in div_cont.find_all("sup"):
        stxt = sup.get_text().strip()
        if stxt.isdigit():
            sup.replace_with(f"-{stxt}")
        else:
            sup.decompose()

    art_regex = re.compile(r"^(?:статья|модда|modda)\s*(\d+(?:-\d+)*)[\.\s:]*(.*)$", re.IGNORECASE)

    articles = {}
    cur_num = None
    cur_title = ""
    cur_p = []

    for ch in div_cont.find_all("div", recursive=False):
        txt = " ".join(ch.get_text().split())
        if not txt:
            continue
        m = art_regex.match(txt)
        if m:
            if cur_num:
                articles[cur_num] = (cur_title, "\n\n".join(cur_p))
            cur_num = m.group(1)
            cur_title = m.group(2).strip()
            cur_p = []
            continue
        if cur_num:
            if not txt.startswith("Ҳужжатга таклиф") and not txt.startswith("Отправить предложение"):
                cur_p.append(txt)

    if cur_num:
        articles[cur_num] = (cur_title, "\n\n".join(cur_p))

    return articles


async def enrich_code(
    http_client: httpx.AsyncClient,
    store: HybridStore,
    slug: str,
    ru_doc_id: str,
    ru_law_title: str,
    catalog_dir: Path,
) -> int:
    json_path = catalog_dir / f"{slug}.json"
    if not json_path.exists():
        logger.warning(f"[{slug}] JSON not found at {json_path}. Skipping.")
        return 0

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    articles = [CanonicalArticle.model_validate(item) for item in data]
    logger.info(f"[{slug}] Loaded {len(articles)} existing articles. Fetching Russian version (ID: {ru_doc_id})...")

    ru_url = f"https://lex.uz/docs/{ru_doc_id}"
    resp = await http_client.get(ru_url)
    if resp.status_code != 200:
        logger.error(f"[{slug}] Failed to fetch Russian doc {ru_url}: HTTP {resp.status_code}")
        return 0

    ru_articles = parse_russian_html(resp.text)
    logger.info(f"[{slug}] Extracted {len(ru_articles)} Russian articles.")

    from datetime import datetime, timezone
    art_num_regex = re.compile(r"(\d+(?:-\d+)*)")
    matched = 0

    with store.fts_store._get_connection() as conn:
        conn.execute("DELETE FROM articles_fts WHERE canonical_id LIKE ?", (f"{slug}_art_%",))
        for art in articles:
            num_m = art_num_regex.search(art.metadata.article_number)
            if not num_m:
                continue
            num_str = num_m.group(1)

            if num_str in ru_articles:
                ru_title, ru_body = ru_articles[num_str]
                art.translations["ru"] = ru_body if ru_body else ru_title
                art.metadata.article_title["ru"] = ru_title
                art.metadata.law_title["ru"] = ru_law_title
                art.translation_provenance["ru"] = TranslationProvenanceType.OFFICIAL
                matched += 1

                json_str = art.model_dump_json()
                conn.execute("""
                    INSERT INTO articles_metadata (
                        canonical_id, json_data, source_hash, status, category, last_verified_date, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_id) DO UPDATE SET
                        json_data = excluded.json_data,
                        updated_at = excluded.updated_at
                """, (
                    art.canonical_id,
                    json_str,
                    art.metadata.source_hash,
                    art.metadata.status.value,
                    art.metadata.category,
                    art.metadata.last_verified_date,
                    datetime.now(timezone.utc).isoformat(),
                ))
                for lang, body in art.translations.items():
                    title = art.get_title(lang)
                    conn.execute("""
                        INSERT INTO articles_fts (
                            canonical_id, language, article_number, law_number, title, body
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        art.canonical_id,
                        lang,
                        art.metadata.article_number,
                        art.metadata.law_number,
                        title,
                        art.to_fts_document(lang),
                    ))
        conn.commit()

    # Save enriched JSON back
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([a.model_dump() for a in articles], f, ensure_ascii=False, indent=2)

    logger.info(f"[{slug}] Successfully enriched {matched}/{len(articles)} articles with official Russian text!")
    return matched


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Enrich Codes with Official Russian Translations")
    parser.add_argument("--codes", nargs="*", help="Specific code slugs to enrich (default: all)")
    args = parser.parse_args()

    catalog_dir = Path("data/laws_catalog")
    store = HybridStore()

    headers = {
        "User-Agent": "UzbekistanLegalRAG/1.0 (Government & Citizen Legal Access Research; contact@legal-rag.uz)",
        "Accept-Language": "ru,uz;q=0.9",
    }

    target_slugs = list(RUSSIAN_CODES_MAP.keys())
    if args.codes:
        target_slugs = [s for s in target_slugs if s in args.codes]

    logger.info(f"Starting Russian enrichment for {len(target_slugs)} codes...")

    total_enriched = 0
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=headers) as http_client:
        for slug in target_slugs:
            ru_doc_id, ru_law_title = RUSSIAN_CODES_MAP[slug]
            try:
                count = await enrich_code(
                    http_client=http_client,
                    store=store,
                    slug=slug,
                    ru_doc_id=ru_doc_id,
                    ru_law_title=ru_law_title,
                    catalog_dir=catalog_dir,
                )
                total_enriched += count
            except Exception as e:
                logger.error(f"Error enriching {slug}: {e}", exc_info=True)

            await asyncio.sleep(1.0)

    logger.info(f"Enrichment completed! Total articles enriched with official Russian text: {total_enriched}")


if __name__ == "__main__":
    asyncio.run(main())
