#!/usr/bin/env python3
"""
Adds the per-chunk full-text rows of long units (FTS_CHUNK_MIN_CHARS) to an existing store. Only the FTS rows of those
units are rewritten; texts, vectors and everything else stay as they are. Safe to repeat.

  python scripts/index_long_units_fts.py            # dry run: how many units and rows
  python scripts/index_long_units_fts.py --run
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.schema.canonical import CanonicalArticle  # noqa: E402
from src.storage.fts_store import SqliteFtsStore, fts_rows  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--store-dir", default=str(ROOT / "data" / "store"))
    args = ap.parse_args()

    store = SqliteFtsStore(str(Path(args.store_dir) / "legal_rag.db"))
    conn = store._get_connection()
    try:
        long_units = []
        for cid, raw in conn.execute("SELECT canonical_id, json_data FROM articles_metadata"):
            art = CanonicalArticle.model_validate_json(raw)
            if any(len(t or "") > settings.FTS_CHUNK_MIN_CHARS for t in art.translations.values()):
                long_units.append(art)
        total_rows = sum(len(fts_rows(a)) for a in long_units)
        print(f"units longer than {settings.FTS_CHUNK_MIN_CHARS} characters: {len(long_units)}; FTS rows for them: {total_rows}")
        if not args.run:
            print("Dry run only. Add --run to write.")
            return 0
        for art in long_units:
            conn.execute("DELETE FROM articles_fts WHERE canonical_id = ?", (art.canonical_id,))
            conn.executemany("INSERT INTO articles_fts (canonical_id, language, article_number, law_number, title, body) "
                             "VALUES (?, ?, ?, ?, ?, ?)", fts_rows(art))
        conn.commit()
        print("rows now:", conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0])
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
