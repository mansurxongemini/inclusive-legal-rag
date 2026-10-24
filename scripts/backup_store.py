#!/usr/bin/env python3
"""
Consistent backup of the knowledge base (data/store).

* every SQLite database is copied with the online backup API (the files are in WAL mode and are written by the running
  server: copying them with tar can produce a database that does not open);
* the LanceDB folder is copied, then opened and its row count compared with the live table (the copy is repeated once
  if a write happened in between);
* the result is checked (integrity_check of each database, vector count) before the folder is announced;
* old backups beyond --keep are removed (only folders this script made: legal_rag_backup_*).

  python scripts/backup_store.py                      # data/backups/legal_rag_backup_<time>/
  python scripts/backup_store.py --dest /mnt/usb --keep 14 --archive
"""
import argparse
import shutil
import sqlite3
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def backup_sqlite(src: Path, dst: Path) -> None:
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=60)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    check = sqlite3.connect(dst)
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        raise RuntimeError(f"{dst.name}: integrity_check says {result}")


def lance_rows(path: Path) -> int:
    import lancedb
    db = lancedb.connect(str(path))
    return len(db.open_table("articles_vectors"))


def backup_lance(src: Path, dst: Path) -> int:
    for attempt in range(2):
        if dst.exists():
            shutil.rmtree(dst)
        before = lance_rows(src)
        shutil.copytree(src, dst)
        copied = lance_rows(dst)
        if copied == before == lance_rows(src):
            return copied
    raise RuntimeError(f"LanceDB copy is not consistent (live {before}, copy {copied}); try again when the server is idle")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=str(ROOT / "data" / "store"))
    ap.add_argument("--dest", default=str(ROOT / "data" / "backups"))
    ap.add_argument("--keep", type=int, default=0, help="keep this many backups made by this script (0 = keep all)")
    ap.add_argument("--archive", action="store_true", help="also write <backup>.tar.gz and remove the folder")
    args = ap.parse_args()

    store, dest_root = Path(args.store), Path(args.dest)
    out = dest_root / f"legal_rag_backup_{time.strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True)
    try:
        for db in sorted(store.glob("*.db")):
            if db.stat().st_size:
                backup_sqlite(db, out / db.name)
                print(f"  {db.name}: ok")
        if (store / "lancedb").is_dir():
            print(f"  lancedb: {backup_lance(store / 'lancedb', out / 'lancedb')} vectors")
        for extra in (".integration_hash_secret",):
            if (store / extra).exists():
                shutil.copy2(store / extra, out / extra)
    except Exception:
        shutil.rmtree(out, ignore_errors=True)
        raise
    final = out
    if args.archive:
        final = out.with_suffix(".tar.gz")
        with tarfile.open(final, "w:gz") as tar:
            tar.add(out, arcname=out.name)
        shutil.rmtree(out)
    if args.keep > 0:
        old = sorted([p for p in dest_root.glob("legal_rag_backup_*")], key=lambda p: p.name)[:-args.keep]
        for p in old:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            print(f"  removed old backup {p.name}")
    print(f"Backup ready: {final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
