#!/usr/bin/env python3
"""
Uzbekistan Legal RAG — Migration: Clean Fake Russian (Uzbek Cyrillic)
Transforms all articles where Uzbek Cyrillic was mistakenly stored as 'ru' translation:
1. Moves text to 'uz_cyrl' (preserving original authentic Cyrillic text).
2. Sets 'ru' to '' (or authentic Russian).
3. Updates SQLite articles_metadata and articles_fts.
4. Updates LanceDB articles_vectors (language = 'uz_cyrl').
"""

import glob
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.nlp.transliteration import is_genuine_russian
import lancedb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def migrate_catalog_and_database(dry_run: bool = False):
    start_time = time.time()
    db_path = Path("data/store/legal_rag.db")
    lance_path = Path("data/store/lancedb")

    logger.info("=" * 65)
    logger.info("🚀 STARTING MIGRATION: SEPARATING UZBEK CYRILLIC FROM RUSSIAN")
    logger.info(f"   Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}")
    logger.info("=" * 65)

    catalog_files = glob.glob("data/laws_catalog/**/*.json", recursive=True)
    catalog_files = [f for f in catalog_files if not f.endswith("_progress.json") and "summary" not in f]
    logger.info(f"📁 Found {len(catalog_files)} catalog JSON files to inspect.")

    total_articles = 0
    fixed_articles = 0
    modified_cids = []

    sqlite_updates = []
    fts_delete_cids = []
    fts_insert_records = []

    for file_path in catalog_files:
        try:
            with open(file_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if not isinstance(data, list):
                continue

            file_modified = False
            for art in data:
                total_articles += 1
                cid = art.get("canonical_id")
                trans = art.get("translations", {})
                ru_text = trans.get("ru", "")

                if ru_text and not is_genuine_russian(ru_text):
                    fixed_articles += 1
                    file_modified = True
                    modified_cids.append(cid)

                    # Move to uz_cyrl
                    trans["uz_cyrl"] = ru_text
                    trans["ru"] = ""

                    prov = art.get("translation_provenance", {})
                    prov["uz_cyrl"] = "official"
                    prov["ru"] = "machine_translated_unreviewed"

                    # Fix points
                    for pt in art.get("points", []):
                        pt_text = pt.get("text", {})
                        if pt_text.get("ru") and not is_genuine_russian(pt_text["ru"]):
                            pt_text["uz_cyrl"] = pt_text["ru"]
                            pt_text["ru"] = ""

                    # Fix metadata titles
                    meta = art.get("metadata", {})
                    lt = meta.get("law_title", {})
                    if lt.get("ru") and not is_genuine_russian(lt["ru"]):
                        lt["uz_cyrl"] = lt["ru"]
                        lt["ru"] = ""

                    at = meta.get("article_title", {})
                    if at.get("ru") and not is_genuine_russian(at["ru"]):
                        at["uz_cyrl"] = at["ru"]
                        at["ru"] = ""

                    if not dry_run:
                        sqlite_updates.append((json.dumps(art, ensure_ascii=False), cid))
                        fts_delete_cids.append((cid,))
                        fts_insert_records.append((
                            cid,
                            "uz_cyrl",
                            meta.get("article_number", ""),
                            meta.get("law_number", ""),
                            at.get("uz_cyrl", ""),
                            ru_text,
                        ))

            if file_modified and not dry_run:
                with open(file_path, "w", encoding="utf-8") as fp:
                    json.dump(data, fp, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")

    logger.info(f"📊 Inspected: {total_articles:,} articles | Fixed fake Russian in: {fixed_articles:,} articles")

    if dry_run or not modified_cids:
        logger.info("Dry run complete. No database changes made.")
        return

    # Update SQLite
    logger.info("💾 Updating SQLite articles_metadata and articles_fts...")
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")

        # Update json_data
        cursor.executemany(
            "UPDATE articles_metadata SET json_data = ? WHERE canonical_id = ?",
            sqlite_updates
        )
        logger.info(f"  ✅ Updated {len(sqlite_updates):,} rows in articles_metadata.")

        # Update FTS
        cursor.executemany(
            "DELETE FROM articles_fts WHERE canonical_id = ? AND language = 'ru'",
            fts_delete_cids
        )
        cursor.executemany(
            "INSERT INTO articles_fts (canonical_id, language, article_number, law_number, title, body) VALUES (?, ?, ?, ?, ?, ?)",
            fts_insert_records
        )
        conn.commit()
        logger.info("  ✅ Updated articles_fts records.")

    # Update LanceDB
    logger.info("⚡ Updating LanceDB language tags...")
    try:
        ldb = lancedb.connect(str(lance_path))
        tbl = ldb.open_table("articles_vectors")
        # In LanceDB, update in batches
        batch_size = 500
        for i in range(0, len(modified_cids), batch_size):
            batch = modified_cids[i:i + batch_size]
            cids_sql = ", ".join(f"'{c}'" for c in batch)
            tbl.update(where=f"canonical_id IN ({cids_sql}) AND language = 'ru'", values={"language": "uz_cyrl"})
            if (i // batch_size) % 10 == 0 or i + batch_size >= len(modified_cids):
                logger.info(f"  LanceDB updated {min(i + batch_size, len(modified_cids)):,}/{len(modified_cids):,} records...")
        logger.info("  ✅ LanceDB language tags successfully migrated to 'uz_cyrl'!")
    except Exception as e:
        logger.error(f"LanceDB update failed: {e}")

    elapsed = time.time() - start_time
    logger.info("=" * 65)
    logger.info(f"🏁 MIGRATION COMPLETE in {elapsed:.1f}s. Fixed {fixed_articles:,} articles across all stores.")
    logger.info("=" * 65)


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    migrate_catalog_and_database(dry_run=is_dry)
