#!/usr/bin/env python3
"""
After a refresh: which open "document/norm amended" notifications are a re-parse only, and which carry new legal text.

A parser change (for example points that followed a repealed point becoming units of their own) makes refresh flag every
touched act as amended, and every Huquq+ post or curated answer linked to it is held back until an editor resolves the
notification. This compares the sentences of each act before and after: an act whose new edition contains no sentence
the old one lacked changed only its unit boundaries. Those notifications can be resolved automatically (--resolve);
the others contain new text from Lex.uz and stay open for the editor.

  python scripts/classify_refresh_changes.py --before data/backups/<backup>/ --after data/store
  python scripts/classify_refresh_changes.py --before ... --after data/store --resolve
"""
import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Set

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESOLUTION = ("Re-parse only: the act's units were split differently; no sentence of the act changed (checked by "
              "scripts/classify_refresh_changes.py). No editorial action needed.")


def sentences(text: str) -> Set[str]:
    t = re.sub(r"\s+", " ", re.sub(r"[ʻʼ‘’`]", "'", text or ""))
    return {s.strip(" .;:,").lower() for s in re.split(r"(?<=[.;:])\s+", t) if len(s.strip()) > 3}


def act_of(canonical_id: str) -> str:
    if canonical_id.startswith("law:"):
        return canonical_id[4:]
    return re.sub(r"_(?:a\d+_)?(?:p|art)_[\d_]+$|_preamble$", "", canonical_id)


def sentences_by_act(store_dir: Path) -> Dict[str, Set[str]]:
    con = sqlite3.connect(f"file:{store_dir / 'legal_rag.db'}?mode=ro", uri=True)
    out: Dict[str, Set[str]] = collections.defaultdict(set)
    for _cid, raw in con.execute("SELECT canonical_id, json_data FROM articles_metadata"):
        d = json.loads(raw)
        out[d["metadata"]["law_id"]] |= sentences((d.get("translations") or {}).get("uz"))
    con.close()
    return out


def classify(before: Dict[str, Set[str]], after: Dict[str, Set[str]], notifications) -> Dict[str, list]:
    """notifications: (id, kind, canonical_id). {'structural': [ids], 'content': [(id, act, new sentences)]}."""
    out: Dict[str, list] = {"structural": [], "content": []}
    for nid, _kind, cid in notifications:
        act = act_of(cid)
        new = after.get(act, set()) - before.get(act, set())
        if new:
            out["content"].append((nid, act, sorted(new)[:3]))
        else:
            out["structural"].append(nid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True, help="store folder before the refresh (a backup)")
    ap.add_argument("--after", required=True, help="store folder after the refresh")
    ap.add_argument("--resolve", action="store_true", help="resolve the re-parse-only notifications in --after")
    args = ap.parse_args()
    after_dir = Path(args.after)
    con = sqlite3.connect(f"file:{after_dir / 'editorial.db'}?mode=ro", uri=True)
    open_rows = con.execute("SELECT id, kind, canonical_id FROM notifications WHERE status = 'open' "
                            "AND kind IN ('document_amended', 'norm_amended')").fetchall()
    con.close()
    result = classify(sentences_by_act(Path(args.before)), sentences_by_act(after_dir), open_rows)
    print(f"re-parse only: {len(result['structural'])}, new text: {len(result['content'])}")
    for nid, act, new in result["content"]:
        print(f"  open #{nid} {act}: {[s[:80] for s in new]}")
    if args.resolve and result["structural"]:
        from src.editorial.store import EditorialStore
        store = EditorialStore(str(after_dir / "editorial.db"))
        for nid in result["structural"]:
            store.resolve_notification(nid, resolution=RESOLUTION, resolved_by="classify_refresh_changes")
        print(f"resolved {len(result['structural'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
