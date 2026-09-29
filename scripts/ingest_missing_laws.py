#!/usr/bin/env python3
"""
Targeted Retry Ingestion for any unindexed laws from data/qonunlar/act_list.doc.
Identifies gaps between act_list.doc and data/store/legal_rag.db,
fetches official Uzbek and Russian texts, checks active status,
and indexes into LanceDB & SQLite FTS5.
"""

import asyncio
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
import httpx

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient
from scripts.ingest_all_laws import parse_act_list_doc, ingest_single_law

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main():
    act_list_file = Path("data/qonunlar/act_list.doc")
    laws_dir = Path("data/laws_catalog/laws")
    laws_dir.mkdir(parents=True, exist_ok=True)

    items = parse_act_list_doc(act_list_file)
    store = HybridStore()
    client = OpenRouterClient()

    # Find missing
    conn = sqlite3.connect(store.fts_store.db_path)
    c = conn.cursor()
    c.execute("SELECT DISTINCT json_extract(json_data, '$.metadata.law_id') FROM articles_metadata")
    indexed_slugs = set(r[0] for r in c.fetchall())

    missing = [it for it in items if it["slug"] not in indexed_slugs]
    logger.info(f"Total laws in act_list: {len(items)}")
    logger.info(f"Already indexed: {len(indexed_slugs)}")
    logger.info(f"Missing laws to process: {len(missing)}")

    if not missing:
        logger.info("All laws from act_list are already fully indexed!")
        return

    headers = {
        "User-Agent": "UzbekistanLegalRAG/1.0 (Government & Citizen Legal Access Research; contact@legal-rag.uz)",
        "Accept-Language": "uz,ru;q=0.9",
    }

    stats = {"processed": 0, "success": 0, "skipped_repealed": 0, "empty": 0, "failed": 0, "articles": 0}
    start_time = time.time()

    async with httpx.AsyncClient(timeout=35.0, follow_redirects=True, headers=headers) as http_client:
        for idx, item in enumerate(missing, 1):
            law_num = item["law_number"]
            slug = item["slug"]
            stats["processed"] += 1

            try:
                res = await ingest_single_law(
                    http_client=http_client,
                    store=store,
                    openrouter_client=client,
                    item=item,
                    laws_dir=laws_dir,
                    batch_size=25,
                )
                st = res.get("status")
                arts = res.get("articles", 0)

                if st == "success":
                    stats["success"] += 1
                    stats["articles"] += arts
                    logger.info(f"[{idx}/{len(missing)}] SUCCESS {law_num} ({slug}): {arts} articles indexed.")
                elif st == "skipped_repealed":
                    stats["skipped_repealed"] += 1
                    logger.info(f"[{idx}/{len(missing)}] REPEALED {law_num}: {res.get('reason')}")
                elif st == "empty_articles":
                    stats["empty"] += 1
                    logger.warning(f"[{idx}/{len(missing)}] EMPTY {law_num} (no articles detected)")
                else:
                    stats["failed"] += 1
                    logger.warning(f"[{idx}/{len(missing)}] FAILED {law_num}: {res.get('error') or st}")

            except Exception as e:
                stats["failed"] += 1
                logger.error(f"[{idx}/{len(missing)}] EXCEPTION {law_num}: {e}")

            await asyncio.sleep(0.5)

    total_time = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"COMPLETED in {total_time:.1f}s. Summary: {json.dumps(stats, indent=2)}")
    logger.info(f"Final store count: {store.count()}")


if __name__ == "__main__":
    asyncio.run(main())
