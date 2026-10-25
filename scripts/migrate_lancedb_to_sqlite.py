#!/usr/bin/env python3
"""
One-time conversion of the vector table of an older store (<store>/lancedb, made by LanceDB) into <store>/vectors.db.

The service no longer uses LanceDB (it crashes on CPUs without AVX2); this tool does, so install it for the conversion
only (it is not in requirements.txt). Use it on the store of an older release, or on an old backup folder:

    .venv/bin/pip install lancedb
    .venv/bin/python scripts/migrate_lancedb_to_sqlite.py --store-dir data/store
    .venv/bin/python scripts/migrate_lancedb_to_sqlite.py --store-dir data/backups/store_before_qwen_20261025 --remove-old

The old folder is left in place unless --remove-old is given (only after the new file was verified).
"""
import argparse
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.storage.vector_store import VectorStore  # noqa: E402

BATCH_UNITS = 500


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store-dir", default=settings.STORAGE_DIR)
    ap.add_argument("--remove-old", action="store_true", help="delete <store>/lancedb after the new file is verified")
    args = ap.parse_args()

    try:
        import lancedb
    except ImportError:
        sys.exit("lancedb is not installed: .venv/bin/pip install lancedb (needed for this conversion only)")

    store_dir = Path(args.store_dir)
    old_dir = store_dir / "lancedb"
    if not old_dir.is_dir():
        sys.exit(f"{old_dir} does not exist: nothing to convert")

    table = lancedb.connect(str(old_dir)).open_table("articles_vectors").to_arrow()
    vectors = table.column("vector").combine_chunks().values.to_numpy(zero_copy_only=False).reshape(table.num_rows, -1)
    meta = table.drop(["vector"]).to_pylist()           # python objects only for the small columns
    allowed = set(settings.vector_language_list)
    by_unit = defaultdict(list)
    skipped = 0
    for i, r in enumerate(meta):
        if r["language"] in allowed:
            by_unit[r["canonical_id"]].append({**r, "vector": vectors[i]})
        else:
            skipped += 1
    print(f"{table.num_rows} rows in LanceDB, {len(by_unit)} units in {sorted(allowed)}, {skipped} rows of other languages skipped")

    store = VectorStore(str(store_dir))
    if store.count():
        sys.exit(f"{store.db_path} already holds {store.count()} rows: remove it first if the conversion is to be repeated")
    units = list(by_unit)
    for i in range(0, len(units), BATCH_UNITS):    # a unit's chunk rows go in one batch: an upsert replaces the unit's rows
        store.upsert_vectors([r for cid in units[i:i + BATCH_UNITS] for r in by_unit[cid]])

    expected = table.num_rows - skipped
    if store.count() != expected or len(store.canonical_ids()) != len(by_unit):
        sys.exit(f"Verification failed: {store.count()} rows / {len(store.canonical_ids())} units, expected {expected} / {len(by_unit)}")
    print(f"{store.db_path}: {store.count()} rows, {len(store.canonical_ids())} units, models {store.models()}, "
          f"{store.size_bytes() // 2**20} MB")
    if args.remove_old:
        shutil.rmtree(old_dir)
        print(f"Removed {old_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
