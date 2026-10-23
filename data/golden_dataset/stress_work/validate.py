#!/usr/bin/env python3
"""Validate a stress-eval batch: ids exist, evidence is a verbatim phrase of an expected unit, schema is complete.
usage: python data/golden_dataset/stress_work/validate.py <batch.json> [...]"""
import json, sys, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
arts = {a["canonical_id"]: a for a in json.loads((ROOT / "data/sources/built_articles.json").read_text(encoding="utf-8"))}
norm = lambda s: " ".join(s.replace("ʻ", "'").replace("ʼ", "'").replace("’", "'").replace("‘", "'").lower().split())
REQ = {"id", "question", "language", "expected_ids", "evidence", "out_of_scope", "domain", "difficulty", "note"}
bad = 0
items = []
for f in sys.argv[1:]:
    items += json.loads(Path(f).read_text(encoding="utf-8"))
ids = collections.Counter(i.get("id") for i in items)
qs = collections.Counter(norm(i.get("question", "")) for i in items)
for it in items:
    errs = []
    miss = REQ - set(it)
    if miss: errs.append(f"missing fields {sorted(miss)}")
    if ids[it.get("id")] > 1: errs.append("duplicate id")
    if qs[norm(it.get("question", ""))] > 1: errs.append("duplicate question")
    if it.get("language") not in ("uz", "ru", "en"): errs.append(f"bad language {it.get('language')}")
    if not it.get("out_of_scope"):
        exp = it.get("expected_ids") or []
        unknown = [e for e in exp if e not in arts]
        if unknown: errs.append(f"unknown ids {unknown}")
        present = [e for e in exp if e in arts]
        ev = norm(it.get("evidence", ""))
        if not ev or len(ev) < 4: errs.append("empty evidence")
        elif present and not any(ev in norm(arts[e]["translations"].get("uz", "") + " " + arts[e]["translations"].get("ru", "")) for e in present):
            errs.append("evidence not found in expected units")
    elif it.get("expected_ids"):
        errs.append("out_of_scope item has expected_ids")
    if errs:
        bad += 1
        print(f"{it.get('id')}: " + "; ".join(errs))
print(f"\n{len(items)} items, {bad} invalid | domains={dict(collections.Counter(i.get('domain') for i in items))}")
print(f"difficulty={dict(collections.Counter(i.get('difficulty') for i in items))}")
print(f"language={dict(collections.Counter(i.get('language') for i in items))} out_of_scope={sum(1 for i in items if i.get('out_of_scope'))}")
sys.exit(1 if bad else 0)
