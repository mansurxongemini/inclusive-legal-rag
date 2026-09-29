#!/usr/bin/env python3
"""
Uzbekistan Legal RAG — Fast Catalog-to-Stores Synchronizer
Synchronizes all catalog JSON files into SQLite (articles_metadata, articles_fts)
and updates LanceDB language tags (uz_cyrl vs ru).
"""

import glob
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
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

def sync_all():
    start_time = time.time()
    db_path = Path("data/store/legal_rag.db")
    lance_path = Path("data/store/lancedb")

    logger.info("=" * 65)
    logger.info("🚀 STARTING FAST CATALOG-TO-STORES SYNC")
    logger.info("=" * 65)

    catalog_files = glob.glob("data/laws_catalog/**/*.json", recursive=True)
    catalog_files = [f for f in catalog_files if not f.endswith("_progress.json") and "summary" not in f]
    logger.info(f"📁 Found {len(catalog_files)} catalog JSON files.")

    total_articles = 0
    uz_cyrl_cids = set()
    metadata_batch = []
    fts_insert_batch = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for file_path in catalog_files:
        try:
            with open(file_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if not isinstance(data, list):
                continue

            for art in data:
                total_articles += 1
                cid = art.get("canonical_id")
                meta = art.get("metadata", {})
                trans = art.get("translations", {})
                
                # Check uz_cyrl
                has_cyrl = bool(trans.get("uz_cyrl"))
                if has_cyrl:
                    uz_cyrl_cids.add(cid)

                # Prepare metadata row
                json_str = json.dumps(art, ensure_ascii=False)
                metadata_batch.append((
                    cid,
                    json_str,
                    meta.get("source_hash", ""),
                    meta.get("status", "active"),
                    meta.get("category", ""),
                    meta.get("last_verified_date", ""),
                    now_iso,
                ))

                # Prepare FTS rows for non-empty translations
                art_num = meta.get("article_number", "")
                law_num = meta.get("law_number", "")
                at_titles = meta.get("article_title", {})

                for lang, body in trans.items():
                    if body and body.strip():
                        t_title = at_titles.get(lang, "")
                        fts_insert_batch.append((
                            cid,
                            lang,
                            art_num,
                            law_num,
                            t_title,
                            f"{t_title} {body}".strip(),
                        ))

        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")

    logger.info(f"📊 Processed {total_articles:,} articles.")
    logger.info(f"   Articles with authentic Cyrillic (uz_cyrl): {len(uz_cyrl_cids):,}")
    logger.info(f"   Total FTS searchable rows to index: {len(fts_insert_batch):,}")

    # 1. Update SQLite
    logger.info("💾 Updating SQLite database...")
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA temp_store=MEMORY;")

        # Upsert articles_metadata
        cursor.executemany("""
            INSERT INTO articles_metadata (
                canonical_id, json_data, source_hash, status, category, last_verified_date, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_id) DO UPDATE SET
                json_data = excluded.json_data,
                source_hash = excluded.source_hash,
                status = excluded.status,
                category = excluded.category,
                last_verified_date = excluded.last_verified_date,
                updated_at = excluded.updated_at
        """, metadata_batch)
        logger.info(f"  ✅ Upserted {len(metadata_batch):,} rows in articles_metadata.")

        # Rebuild articles_fts
        logger.info("  Rebuilding articles_fts...")
        cursor.execute("DELETE FROM articles_fts;")
        cursor.executemany("""
            INSERT INTO articles_fts (canonical_id, language, article_number, law_number, title, body)
            VALUES (?, ?, ?, ?, ?, ?)
        """, fts_insert_batch)
        conn.commit()
        logger.info(f"  ✅ Inserted {len(fts_insert_batch):,} clean rows in articles_fts.")

    # 2. Update LanceDB
    logger.info("⚡ Updating LanceDB language tags...")
    try:
        ldb = lancedb.connect(str(lance_path))
        tbl = ldb.open_table("articles_vectors")
        
        # Batch update uz_cyrl in LanceDB
        cyrl_list = list(uz_cyrl_cids)
        batch_size = 500
        for i in range(0, len(cyrl_list), batch_size):
            batch = cyrl_list[i:i + batch_size]
            cids_sql = ", ".join(f"'{c}'" for c in batch)
            tbl.update(
                where=f"canonical_id IN ({cids_sql}) AND language = 'ru'",
                values={"language": "uz_cyrl"}
            )
            if (i // batch_size) % 20 == 0 or i + batch_size >= len(cyrl_list):
                logger.info(f"  LanceDB updated {min(i + batch_size, len(cyrl_list)):,}/{len(cyrl_list):,} records...")

        logger.info("  ✅ LanceDB vectors successfully synchronized!")
    except Exception as e:
        logger.error(f"LanceDB update notice: {e}")

    elapsed = time.time() - start_time
    logger.info("=" * 65)
    logger.info(f"🏁 SYNC COMPLETE in {elapsed:.1f}s.")
    logger.info("=" * 65)

if __name__ == "__main__":
    sync_all()
