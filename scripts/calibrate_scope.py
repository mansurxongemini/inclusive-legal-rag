#!/usr/bin/env python3
"""
How well does the Jev scope question separate in-scope from out-of-scope questions?

Runs JevRanker.scope() on labelled questions and prints, for several thresholds, how many in-scope questions would be
refused (false refusals) and how many out-of-scope questions would be refused. The labels come from the stress set
(items marked scope=ambiguous are skipped) and optional extra files in the held-out format
({"in_scope": [{"question": ...}], "out_of_scope": [{"question": ...}]}). Nothing is written to src/.

  python scripts/calibrate_scope.py --extra data/golden_dataset/heldout_v1.json
  python scripts/calibrate_scope.py --criteria-file variant.json    # {"in_scope": "...", "other_law": "..."} replaces criteria
"""
import argparse
import asyncio
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402

from src.api.middleware.security import sanitize_user_input  # noqa: E402
from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.retrieval import jev_ranker  # noqa: E402


def load(args):
    items = []
    for it in json.loads(Path(args.dataset).read_text(encoding="utf-8")):
        if it.get("scope") == "ambiguous":
            continue
        items.append({"id": it["id"], "question": it["question"], "oos": bool(it.get("out_of_scope")),
                      "src": "stress", "kind": it.get("difficulty")})
    for path in args.extra:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for n, it in enumerate(data.get("in_scope", [])):
            if it.get("question") and not it.get("skip"):
                items.append({"id": f"{Path(path).stem}:in{n}", "question": it["question"], "oos": False,
                              "src": Path(path).stem, "kind": it.get("style")})
        for n, it in enumerate(data.get("out_of_scope", [])):
            items.append({"id": f"{Path(path).stem}:oos{n}", "question": it["question"], "oos": True,
                          "src": Path(path).stem, "kind": it.get("kind")})
    return items


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(ROOT / "data" / "golden_dataset" / "stress_eval_200.json"))
    ap.add_argument("--extra", action="append", default=[])
    ap.add_argument("--criteria-file", default="")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.criteria_file:
        jev_ranker.SCOPE_QUESTION = copy.deepcopy(jev_ranker.SCOPE_QUESTION)
        jev_ranker.SCOPE_QUESTION["criteria"].update(json.loads(Path(args.criteria_file).read_text(encoding="utf-8")))

    items = load(args)
    client = OpenRouterClient()
    ranker = jev_ranker.JevRanker(client)
    sem = asyncio.Semaphore(args.concurrency)

    async def one(it):
        try:
            q = sanitize_user_input(it["question"])
        except HTTPException:
            it["blocked"] = True                  # refused before retrieval, never reaches the scope question
            return it
        async with sem:
            it["in_scope"] = await ranker.scope(q)
        return it

    items = await asyncio.gather(*(one(i) for i in items))
    await client.close()
    scored = [i for i in items if i.get("in_scope") is not None]
    ins, oos = [i for i in scored if not i["oos"]], [i for i in scored if i["oos"]]
    print(f"in-scope {len(ins)}  out-of-scope {len(oos)}  blocked by sanitizer {sum(1 for i in items if i.get('blocked'))}"
          f"  no score {sum(1 for i in items if not i.get('blocked') and i.get('in_scope') is None)}")
    print(f"{'threshold':>9} {'false refusals':>16} {'OOS refused':>14}")
    for t in (0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        fr = [i for i in ins if i["in_scope"] < t]
        ref = [i for i in oos if i["in_scope"] < t]
        print(f"{t:9.2f} {len(fr):>8} ({100 * len(fr) / max(1, len(ins)):4.1f}%) {len(ref):>6} ({100 * len(ref) / max(1, len(oos)):4.1f}%)")
    t = 0.3
    print(f"\nin-scope questions below {t}:")
    for i in sorted((i for i in ins if i["in_scope"] < t), key=lambda i: i["in_scope"]):
        print(f"  {i['in_scope']:.2f} {i['id']} [{i['kind']}] {i['question'][:110]}")
    print(f"out-of-scope questions at or above {t}:")
    for i in sorted((i for i in oos if i["in_scope"] >= t), key=lambda i: -i["in_scope"]):
        print(f"  {i['in_scope']:.2f} {i['id']} [{i['kind']}] {i['question'][:110]}")
    if args.out:
        Path(args.out).write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
