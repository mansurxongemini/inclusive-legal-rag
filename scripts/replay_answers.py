#!/usr/bin/env python3
"""
Answer-stage experiments without retrieval: the contexts of an earlier stress report are loaded from the store (no embedding,
no Jev: OpenRouter is not touched) and the answer is generated, optionally with the claim check, and judged on the generation
provider.

  python scripts/replay_answers.py --contexts final_e2e_dev.json --arms off,on --report replay.json
"""
import argparse
import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SPEND_SCOPE", "eval")
os.environ.setdefault("OPENROUTER_PAUSED", "true")        # replay never needs OpenRouter

from src.config import settings  # noqa: E402
from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.generation.answer_checks import check_answer  # noqa: E402
from src.generation.generator import AnswerGenerator  # noqa: E402
from src.generation.guards import source_texts  # noqa: E402
from src.nlp.query_analyzer import QueryAnalyzer  # noqa: E402
from src.retrieval.passages import focus_chunks  # noqa: E402
from src.retrieval.reranker import RetrievedArticleContext  # noqa: E402
from src.storage.hybrid_store import HybridStore  # noqa: E402

spec = importlib.util.spec_from_file_location("stress_eval", ROOT / "scripts" / "stress_eval.py")
stress_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stress_eval)


def load_contexts(store, item, report_row):
    arts = store.get_articles_batch(report_row["context_ids"])
    out = []
    for cid in report_row["context_ids"]:
        art = arts.get(cid)
        if art is not None:
            out.append(RetrievedArticleContext(article=art, final_score=1.0, source_tag="primary",
                                               focus=focus_chunks(art, item["question"], ("uz", "ru"))))
    return out


async def run_arm(arm, items, rows, store, client, judge_model, concurrency):
    settings.SUPPORT_CHECK_ENABLED = arm == "on"
    sem = asyncio.Semaphore(concurrency)
    gen = AnswerGenerator(client=client)

    async def one(item):
        async with sem:
            contexts = load_contexts(store, item, rows[item["id"]])
            analysis = QueryAnalyzer.analyze(item["question"])
            t0 = time.perf_counter()
            try:
                res = await gen.generate_answer(query=item["question"], contexts=contexts, language=analysis.detected_language, mode="plain")
            except Exception as e:
                return {"id": item["id"], "error": str(e)[:200]}
            latency = round((time.perf_counter() - t0) * 1000)
            text = res.clean_answer or res.answer
            out = {"id": item["id"], "answer": text, "cited_ids": [c.canonical_id for c in res.citations], "warnings": res.warnings,
                   "latency_ms": latency, "out_of_scope": False, "cited_expected": any(c.canonical_id in item["expected_ids"] for c in res.citations)}
            out["checks"] = check_answer(item["question"], text, source_texts(contexts, analysis.detected_language),
                                         [c.article.canonical_id for c in contexts], analysis.detected_language)
            out["judge"] = await stress_eval.judge_answer(item, out, store, client, judge_model)
            return out

    return await asyncio.gather(*(one(i) for i in items))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contexts", required=True, help="stress report with context_ids per item")
    ap.add_argument("--dataset", default=str(ROOT / "data" / "golden_dataset" / "stress_eval_200.json"))
    ap.add_argument("--arms", default="off,on")
    ap.add_argument("--judge-model", default="muse-spark-1.2")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    rows = {r["id"]: r for r in json.loads(Path(args.contexts).read_text(encoding="utf-8"))["items"]}
    data = {i["id"]: i for i in json.loads(Path(args.dataset).read_text(encoding="utf-8"))}
    items = [data[i] for i, r in rows.items() if i in data and not data[i].get("out_of_scope") and data[i].get("expected_ids") and r.get("context_ids")]
    if args.limit:
        items = items[:args.limit]
    store, client = HybridStore(str(ROOT / "data" / "store")), OpenRouterClient()
    report = {}
    for arm in args.arms.split(","):
        results = await run_arm(arm, items, rows, store, client, args.judge_model, args.concurrency)
        ok = [r for r in results if "error" not in r]
        verdict = lambda v: round(100 * sum(1 for r in ok if r["judge"].get("verdict") == v) / max(1, len(ok)), 1)  # noqa: E731
        dropped = sum(1 for r in ok if any("dropped" in w or "regenerated" in w for w in r["warnings"]))
        report[arm] = {"n": len(ok), "errors": len(results) - len(ok), "correct": verdict("correct"), "partial": verdict("partial"),
                       "wrong": verdict("wrong"), "avg_latency_ms": round(sum(r["latency_ms"] for r in ok) / max(1, len(ok))),
                       "claim_check_changed": dropped, "items": results}
        print(arm, {k: v for k, v in report[arm].items() if k != "items"}, flush=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
