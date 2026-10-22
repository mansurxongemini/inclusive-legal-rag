#!/usr/bin/env python3
"""
Samples legal units for a held-out question set. A question written from a unit has that unit as its known answer
(expected_ids), the same way data/golden_dataset/stress_eval_200.json was built; units that already answer a question of
an existing evaluation set are excluded, so the new set measures cases the system was never tuned on.

  python scripts/sample_heldout_units.py --n 80 --seed 20261022 --out units.json
"""
import argparse
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "data" / "golden_dataset"
EXISTING = ["stress_eval_200.json", "practical_eval_set_v2.json", "practical_eval_set.json", "disability_eval_set.json"]
DISABILITY = re.compile(r"nogiron|nogironlik|imkoniyati cheklangan|reabilitats|protez|tibbiy-ijtimoiy|TIEK|"
                        r"ijtimoiy xizmat|ijtimoiy himoya|inklyuziv|nafaqa|pensiya", re.I)
SKIP_PREFIX = ("hp_", "qa_")


def used_ids() -> set:
    used = set()
    for name in EXISTING:
        path = GOLDEN / name
        if path.exists():
            for item in json.loads(path.read_text(encoding="utf-8")):
                used.update(item.get("expected_ids") or [])
    return used


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--min-chars", type=int, default=250)
    ap.add_argument("--max-chars", type=int, default=2500, help="unit text shown to the question writer")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    used = used_ids()
    con = sqlite3.connect(f"file:{ROOT / 'data' / 'store' / 'legal_rag.db'}?mode=ro", uri=True)
    pool = []
    for cid, raw in con.execute("select canonical_id, json_data from articles_metadata where status='active'"):
        if cid.startswith(SKIP_PREFIX) or cid in used:
            continue
        data = json.loads(raw)
        uz = (data.get("translations") or {}).get("uz") or ""
        meta = data.get("metadata") or {}
        title = (meta.get("law_title") or {}).get("uz", "")
        if len(uz) < args.min_chars or not DISABILITY.search(title + " " + uz[:1500]):
            continue
        pool.append((cid, meta, uz, bool((data.get("translations") or {}).get("ru"))))

    rng = random.Random(args.seed)
    by_act = {}
    for item in pool:
        by_act.setdefault(item[1].get("law_id"), []).append(item)
    acts = sorted(by_act)
    rng.shuffle(acts)
    picked = []
    while len(picked) < args.n and acts:        # round-robin over acts: no act dominates the sample
        for act in list(acts):
            if not by_act[act]:
                acts.remove(act)
                continue
            picked.append(by_act[act].pop(rng.randrange(len(by_act[act]))))
            if len(picked) >= args.n:
                break
    out = [{
        "expected_id": cid,
        "law_number": meta.get("law_number"),
        "law_title": (meta.get("law_title") or {}).get("uz"),
        "unit": meta.get("article_number"),
        "has_ru": has_ru,
        "chars": len(uz),
        "text": uz[: args.max_chars],
    } for cid, meta, uz, has_ru in picked]
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"pool={len(pool)} acts={len(by_act)} picked={len(out)} excluded_used={len(used)} -> {args.out}")


if __name__ == "__main__":
    sys.exit(main())
