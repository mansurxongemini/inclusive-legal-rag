#!/usr/bin/env python3
"""
Retrieval evaluation on the golden set (see src/evaluation/retrieval_eval.py).

  python scripts/evaluate_retrieval.py                       # real store + real embeddings
  python scripts/evaluate_retrieval.py --store-dir data/store --dataset data/golden_dataset/disability_eval_set.json
  python scripts/evaluate_retrieval.py --no-gate             # ranking quality only
  python scripts/evaluate_retrieval.py --calibrate           # suggest gate thresholds from this dataset
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.evaluation.retrieval_eval import RetrievalEvaluator  # noqa: E402
from src.storage.hybrid_store import HybridStore  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store-dir", default=str(ROOT / "data" / "store"))
    ap.add_argument("--dataset", default=str(ROOT / "data" / "golden_dataset" / "disability_eval_set.json"))
    ap.add_argument("--no-gate", action="store_true")
    ap.add_argument("--no-rerank", action="store_true", help="skip the cross-encoder; rank by fused scores only")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--report", default=str(ROOT / "data" / "golden_dataset" / "last_report.json"))
    ap.add_argument("--min-mrr", type=float, default=0.0, help="exit with 1 when MRR is below this value")
    args = ap.parse_args()

    store = HybridStore(args.store_dir)
    client = OpenRouterClient()
    mode = "MOCK embeddings" if client.is_mock else f"live embeddings ({client.embedding_model})"
    print(f"store={args.store_dir} articles={store.count()} | {mode} | gate={'off' if args.no_gate else 'on'}")

    ev = RetrievalEvaluator(store, client=client, apply_gate=not args.no_gate, use_reranker=not args.no_rerank)
    rep = await ev.evaluate(args.dataset)
    await client.close()

    print(f"\nquestions: {rep.total}  (in-scope {rep.in_scope}, out-of-scope {rep.out_of_scope})")
    print(f"hit@1 {rep.hit_at_1:.1%}   hit@3 {rep.hit_at_3:.1%}   hit@5 {rep.hit_at_5:.1%}   MRR {rep.mrr:.3f}")
    print(f"candidate pool (before rerank): hit@10 {rep.pool_hit_at_10:.1%}   hit@30 {rep.pool_hit_at_30:.1%}")
    print(f"false refusals (in-scope refused): {rep.false_refusal_rate:.1%}   correct refusals (out-of-scope): {rep.correct_refusal_rate:.1%}")
    print(f"avg latency {rep.avg_latency_ms:.0f} ms")
    for lg, m in rep.by_language.items():
        print(f"  [{lg}] n={m['n']} hit@3={m['hit@3']:.1%} mrr={m['mrr']:.3f}")
    if rep.failures:
        print(f"\n{len(rep.failures)} problem item(s):")
        for f in rep.failures[:25]:
            print(f"  {f['id']}: {f['question'][:70]!r}\n      expected={f['expected'][:3]} returned={f['returned'][:3]} refused={f['refused']} ({f['gate']}, vec={f['vector']})")

    if rep.coverage_gaps:
        print(f"\n{len(rep.coverage_gaps)} coverage gap(s) (none of the expected acts is in the store):")
        for g in rep.coverage_gaps[:25]:
            print(f"  {g['id']}: {g['question'][:70]!r}\n      expected_law_numbers={g['expected_law_numbers']} lex_ids={g['expected_lex_ids']}")

    if args.calibrate:
        for label, key in (("dense similarity", "best_vector_score"), ("reranker score", "top_rerank_score")):
            ins = sorted(getattr(r, key) for r in rep.items if not r.out_of_scope and getattr(r, key) is not None)
            outs = sorted(getattr(r, key) for r in rep.items if r.out_of_scope and getattr(r, key) is not None)
            if ins and outs:
                p10_in, max_out = ins[max(0, int(len(ins) * 0.1) - 1)], outs[-1]
                verdict = "separable" if p10_in > max_out else "OVERLAPPING"
                print(f"\ncalibration [{label}]: in-scope p10={p10_in:.3f} min={ins[0]:.3f} | out-of-scope max={max_out:.3f} -> "
                      f"threshold ~ {round((p10_in + max_out) / 2, 3)} ({verdict})")

    Path(args.report).write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nreport -> {args.report}")
    return 1 if rep.mrr < args.min_mrr else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
