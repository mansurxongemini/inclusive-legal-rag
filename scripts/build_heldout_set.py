#!/usr/bin/env python3
"""
Turns the question-writer output ({"in_scope": [...], "out_of_scope": [...]}) into the stress_eval format and checks it:
every expected unit must exist, every question must differ from the unit text (no copying), the evidence quote must be
found in the unit, and no question may repeat one of the existing evaluation sets. Writes the dataset plus a manifest
with the sha256 of the file, so that the set can be proven unchanged when it is read at the end of the work.

  python scripts/build_heldout_set.py --questions q.json --out data/golden_dataset/heldout_v1.json
"""
import argparse
import difflib
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "data" / "golden_dataset"


def norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", (text or "").lower().replace("ʻ", "'").replace("‘", "'").replace("’", "'")).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    raw = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    con = sqlite3.connect(f"file:{ROOT / 'data' / 'store' / 'legal_rag.db'}?mode=ro", uri=True)
    existing = []
    for name in ("stress_eval_200.json", "practical_eval_set_v2.json", "practical_eval_set.json"):
        path = GOLDEN / name
        if path.exists():
            existing += [norm(i["question"]) for i in json.loads(path.read_text(encoding="utf-8"))]

    items, rejected = [], []
    for n, it in enumerate(raw.get("in_scope", [])):
        why = None
        if it.get("skip") or not it.get("question"):
            why = "skipped by the writer"
        else:
            row = con.execute("select json_data from articles_metadata where canonical_id=?", (it["expected_id"],)).fetchone()
            if not row:
                why = "unknown unit"
            else:
                data = json.loads(row[0])
                uz = (data.get("translations") or {}).get("uz", "")
                q = norm(it["question"])
                if it.get("evidence") and norm(it["evidence"]) not in norm(uz) and norm(it["evidence"]) not in norm((data.get("translations") or {}).get("ru", "")):
                    why = "evidence is not a quotation of the unit"
                elif difflib.SequenceMatcher(None, q, norm(uz)[:600]).ratio() > 0.6:
                    why = "question copies the unit"
                elif any(difflib.SequenceMatcher(None, q, e).ratio() > 0.85 for e in existing):
                    why = "duplicates an existing evaluation question"
        if why:
            rejected.append({"index": n, "id": it.get("expected_id"), "why": why})
            continue
        meta = data["metadata"]
        items.append({
            "id": f"h{len(items) + 1:03d}", "question": it["question"].strip(), "language": it.get("language", "uz"),
            "expected_ids": [it["expected_id"]], "evidence": it.get("evidence", ""), "out_of_scope": False,
            "domain": meta.get("category") or "unknown", "difficulty": it.get("style", "colloquial"),
            "note": f"{meta.get('law_number')} {meta.get('article_number')}",
        })
    for it in raw.get("out_of_scope", []):
        if not it.get("question"):
            continue
        items.append({
            "id": f"h{len(items) + 1:03d}", "question": it["question"].strip(), "language": it.get("language", "uz"),
            "expected_ids": [], "evidence": "", "out_of_scope": True, "domain": "out_of_scope",
            "difficulty": "injection" if it.get("kind") == "injection" else f"oos_{it.get('kind', 'other')}",
            "note": it.get("note", ""),
            **({"scope": it["scope"]} if it.get("scope") else {}),
        })

    out = Path(args.out)
    out.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (out.with_suffix(".manifest.json")).write_text(json.dumps({
        "file": out.name, "sha256": digest, "in_scope": sum(1 for i in items if not i["out_of_scope"]),
        "out_of_scope": sum(1 for i in items if i["out_of_scope"]), "rejected": rejected,
        "rule": "never used to tune; read at the start and at the end of the work",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"in_scope={sum(1 for i in items if not i['out_of_scope'])} out_of_scope={sum(1 for i in items if i['out_of_scope'])}"
          f" rejected={len(rejected)} sha256={digest[:12]} -> {out}")
    for r in rejected[:15]:
        print("  rejected", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
