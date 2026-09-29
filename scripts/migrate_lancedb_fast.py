#!/usr/bin/env python3
"""
Fast one-shot migration of LanceDB language tags:
Loads table to PyArrow (~1.1 GB memory), maps canonical_ids having authentic Cyrillic to 'uz_cyrl',
and overwrites table in a single transaction.
"""

import sqlite3
import time
import logging
from pathlib import Path
import lancedb
import pyarrow as pa
import pyarrow.compute as pc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def migrate_lancedb_fast():
    start = time.time()
    logger.info("🚀 Starting fast one-shot LanceDB language migration...")

    # 1. Get canonical_ids that have uz_cyrl from SQLite
    db_path = Path("data/store/legal_rag.db")
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT canonical_id FROM articles_metadata
            WHERE json_extract(json_data, '$.translations.uz_cyrl') IS NOT NULL
              AND json_extract(json_data, '$.translations.uz_cyrl') != ''
        """)
        cyrl_cids = set(row[0] for row in c.fetchall())

    logger.info(f"Loaded {len(cyrl_cids):,} canonical_ids with authentic Cyrillic from SQLite.")

    # 2. Connect to LanceDB and load arrow table
    lance_path = Path("data/store/lancedb")
    ldb = lancedb.connect(str(lance_path))
    tbl = ldb.open_table("articles_vectors")
    
    logger.info("Reading LanceDB table to Arrow...")
    arrow_tbl = tbl.to_arrow()
    total_rows = arrow_tbl.num_rows
    logger.info(f"Loaded {total_rows:,} rows from LanceDB.")

    # 3. Update language column in memory
    cids = arrow_tbl.column("canonical_id").to_pylist()
    langs = arrow_tbl.column("language").to_pylist()

    new_langs = []
    converted = 0
    for cid, lang in zip(cids, langs):
        if lang == "ru" and cid in cyrl_cids:
            new_langs.append("uz_cyrl")
            converted += 1
        else:
            new_langs.append(lang)

    logger.info(f"Converted {converted:,} rows from 'ru' to 'uz_cyrl'.")

    # Replace language column
    lang_col_idx = arrow_tbl.schema.get_field_index("language")
    new_lang_array = pa.array(new_langs, type=pa.string())
    updated_tbl = arrow_tbl.set_column(lang_col_idx, "language", new_lang_array)

    # 4. Overwrite LanceDB table cleanly in ONE commit
    logger.info("Writing updated dataset to LanceDB (single commit)...")
    ldb.create_table("articles_vectors", data=updated_tbl, mode="overwrite")
    
    elapsed = time.time() - start
    logger.info(f"✅ LanceDB migration successfully completed in {elapsed:.1f}s!")

if __name__ == "__main__":
    migrate_lancedb_fast()
