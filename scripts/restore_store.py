#!/usr/bin/env python3
"""
Restore data/store from a backup made by backup_store.py (a folder or a .tar.gz).

The current store is first moved to data/backups/pre_restore_<time>/ so that nothing is lost, and the server must be
stopped (--force overrides the check). The restored databases are checked before the command reports success.

  python scripts/restore_store.py data/backups/legal_rag_backup_20261022_2130
"""
import argparse
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def server_running(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=2)
        return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("backup")
    ap.add_argument("--store", default=str(ROOT / "data" / "store"))
    ap.add_argument("--health-url", default="http://127.0.0.1:8000/health")
    ap.add_argument("--force", action="store_true", help="restore although the server answers on the health URL")
    args = ap.parse_args()

    if server_running(args.health_url) and not args.force:
        print(f"The server answers on {args.health_url}: stop it first (or use --force).", file=sys.stderr)
        return 2
    src = Path(args.backup)
    tmp = None
    if src.is_file():
        tmp = tempfile.mkdtemp(prefix="restore_")
        with tarfile.open(src) as tar:
            tar.extractall(tmp, filter="data")
        src = next(Path(tmp).iterdir())
    if not src.is_dir() or not any(src.glob("*.db")):
        print(f"{src} is not a backup folder (no *.db files).", file=sys.stderr)
        return 1
    for db in src.glob("*.db"):
        con = sqlite3.connect(db)
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        con.close()
        if ok != "ok":
            print(f"{db.name} in the backup is damaged: {ok}", file=sys.stderr)
            return 1

    store = Path(args.store)
    safety = ROOT / "data" / "backups" / f"pre_restore_{time.strftime('%Y%m%d_%H%M%S')}"
    safety.parent.mkdir(parents=True, exist_ok=True)
    if store.exists():
        shutil.move(str(store), str(safety))
        print(f"Current store moved to {safety}")
    shutil.copytree(src, store)
    print(f"Restored {src} -> {store}")
    for db in sorted(store.glob("*.db")):
        con = sqlite3.connect(db)
        print(f"  {db.name}: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
        con.close()
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
