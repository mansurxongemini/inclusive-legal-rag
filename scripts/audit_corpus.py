#!/usr/bin/env python3
"""
Quality gate of the stored corpus (src/ingestion/corpus_audit.py): exit 1 when a unit has no Uzbek text, a broken
character, HTML in its text or a source link that is not a Lex.uz document. Glued headings and swallowed points are
reported, not failed. Read-only; run it after every build, ingest or refresh.

  python scripts/audit_corpus.py                       # data/store
  python scripts/audit_corpus.py --store-dir /path/to/store --report audit.json
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingestion.corpus_audit import audit  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store-dir", default=str(ROOT / "data" / "store"))
    ap.add_argument("--report", default="")
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{Path(args.store_dir) / 'legal_rag.db'}?mode=ro", uri=True)
    units = []
    for cid, raw in con.execute("SELECT canonical_id, json_data FROM articles_metadata"):
        d = json.loads(raw)
        meta = d.get("metadata") or {}
        tr = d.get("translations") or {}
        units.append((cid, tr.get("uz") or "", meta.get("source_url") or "", meta.get("source_type") or "lex",
                      tr.get("ru") or ""))
    con.close()
    result = audit(units)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    print(text)
    return 1 if result["hard"] else 0


if __name__ == "__main__":
    sys.exit(main())
