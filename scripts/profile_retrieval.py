#!/usr/bin/env python3
"""
Where does retrieval time go? Runs the production retrieval path on a sample of the stress questions one at a time
(no concurrency, so timings are not mixed up) and prints, per stage, how often it ran and its mean / p50 / max seconds
as well as how many seconds of the question's wall time it explains. Nothing in src/ is modified: the stage functions
are wrapped at run time.

  python scripts/profile_retrieval.py --limit 12
"""
import argparse
import asyncio
import collections
import json
import statistics
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SPEND_SCOPE", "eval")      # evaluation spend is counted apart and never limited by the service budget

from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.nlp.query_analyzer import QueryAnalyzer  # noqa: E402
from src.nlp.query_translator import QueryTranslator  # noqa: E402
from src.retrieval import hybrid_retriever, jev_ranker, pipeline, reranker  # noqa: E402
from src.storage.hybrid_store import HybridStore  # noqa: E402

TIMINGS = collections.defaultdict(list)


def timed(owner, name, label):
    original = getattr(owner, name)

    async def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return await original(*args, **kwargs)
        finally:
            TIMINGS[label].append(time.perf_counter() - t0)

    setattr(owner, name, wrapper)


def install():
    timed(hybrid_retriever.HybridRetriever, "retrieve", "retriever.retrieve (BM25+embed+vector)")
    timed(OpenRouterClient, "get_embeddings", "  embeddings API")
    timed(QueryTranslator, "to_uzbek", "translate ru/en -> uz (LLM)")
    timed(QueryTranslator, "normalize_uzbek", "normalize uz (LLM)")
    timed(jev_ranker.JevRanker, "scope", "jev scope")
    timed(jev_ranker.JevRanker, "rank", "jev rank")
    timed(reranker.Reranker, "rerank", "reranker.rerank (incl. store reads)")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(ROOT / "data" / "golden_dataset" / "stress_eval_200.json"))
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--stride", type=int, default=0, help="take every n-th question (default: spread over the file)")
    args = ap.parse_args()

    items = [i for i in json.loads(Path(args.dataset).read_text(encoding="utf-8"))]
    stride = args.stride or max(1, len(items) // args.limit)
    items = items[::stride][: args.limit]
    store, client = HybridStore(str(ROOT / "data" / "store")), OpenRouterClient()
    install()
    walls = []
    for it in items:
        analysis = QueryAnalyzer.analyze(it["question"], user_language=it.get("language") or "auto")
        t0 = time.perf_counter()
        await pipeline.retrieve_contexts(analysis=analysis, store=store, client=client, top_k=40, max_extra=8,
                                         rerank_top_n=8)
        walls.append(time.perf_counter() - t0)
        print(f"{it['id']} {it.get('language')} {walls[-1]:6.1f}s", flush=True)
    await client.close()
    print(f"\nquestions={len(walls)} wall mean={statistics.mean(walls):.1f}s p50={statistics.median(walls):.1f}s "
          f"max={max(walls):.1f}s")
    print(f"{'stage':44} {'calls':>5} {'mean':>7} {'p50':>7} {'max':>7} {'sum/wall':>9}")
    for label, vals in sorted(TIMINGS.items()):
        print(f"{label:44} {len(vals):5d} {statistics.mean(vals):7.2f} {statistics.median(vals):7.2f} "
              f"{max(vals):7.2f} {sum(vals) / sum(walls):9.2f}")


if __name__ == "__main__":
    asyncio.run(main())
