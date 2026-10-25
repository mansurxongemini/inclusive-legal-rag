#!/usr/bin/env python3
"""
Dense-only retrieval on the gold set: the question is embedded with the configured model and searched in the vector
table alone (no full-text search, no ranking model), so two embedding models can be compared on their own. It also
reports the best dense score of in-corpus and out-of-corpus questions against GATE_MIN_VECTOR_SCORE (the relevance gate's
"dense_match" threshold, used when the ranking model is unavailable). The
configuration comes from the environment, as for the service (STORAGE_DIR, EMBEDDING_MODEL, EMBEDDING_REQUEST_DIMENSIONS,
EMBEDDING_QUERY_INSTRUCTION). Costs a few hundredths of a cent: only the 76 questions are embedded.

  python eval/dense_only.py                                         # production settings
  STORAGE_DIR=/copy EMBEDDING_MODEL=qwen/qwen3-embedding-8b EMBEDDING_REQUEST_DIMENSIONS=1024 \
      EMBEDDING_QUERY_INSTRUCTION="..." python eval/dense_only.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("SPEND_SCOPE", "eval")

from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.config import settings  # noqa: E402
from src.storage.hybrid_store import HybridStore  # noqa: E402


async def main() -> int:
    items = [json.loads(line) for line in (ROOT / "eval" / "gold_set.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    refused = [i for i in items if i.get("expect_refusal")]
    items = [i for i in items if i.get("expected")]
    store, client = HybridStore(settings.STORAGE_DIR), OpenRouterClient()
    vectors = await client.get_query_embeddings([i["question"] for i in items + refused])
    await client.close()
    best_out = [max((h["score"] for h in store.vector_store.search_vector(v, top_k=5, language="uz")), default=0.0)
                for v in vectors[len(items):]]
    rows, best_in = [], []
    for item, vec in zip(items, vectors):
        hits = store.vector_store.search_vector(vec, top_k=20, language="uz")
        best_in.append(max((h["score"] for h in hits), default=0.0))
        ids = []
        for h in hits:
            if h["canonical_id"] not in ids:
                ids.append(h["canonical_id"])
        wanted = {c for slot in item["expected"] for c in slot}
        rank = next((n + 1 for n, cid in enumerate(ids) if cid in wanted), None)
        slots5 = sum(any(c in ids[:5] for c in slot) for slot in item["expected"]) / len(item["expected"])
        slots20 = sum(any(c in ids[:20] for c in slot) for slot in item["expected"]) / len(item["expected"])
        rows.append({"id": item["id"], "language": item["language"], "rank": rank, "recall@5": slots5, "recall@20": slots20})
    def agg(sub):
        return {"n": len(sub), "recall@5": round(sum(r["recall@5"] for r in sub) / len(sub), 3),
                "recall@20": round(sum(r["recall@20"] for r in sub) / len(sub), 3),
                "mrr@20": round(sum(1 / r["rank"] for r in sub if r["rank"]) / len(sub), 3)}
    out = {"model": settings.EMBEDDING_MODEL, "dimensions": settings.EMBEDDING_REQUEST_DIMENSIONS or "native",
           "instruction": bool(settings.EMBEDDING_QUERY_INSTRUCTION), "all": agg(rows),
           "by_language": {lang: agg([r for r in rows if r["language"] == lang]) for lang in ("uz", "ru", "en")},
           "gate": {"threshold": settings.GATE_MIN_VECTOR_SCORE,
                    "in_corpus": {"n": len(best_in), "min": round(min(best_in), 3), "median": round(sorted(best_in)[len(best_in) // 2], 3),
                                  "passing": sum(b >= settings.GATE_MIN_VECTOR_SCORE for b in best_in)},
                    "out_of_corpus": {"n": len(best_out), "max": round(max(best_out, default=0.0), 3),
                                      "passing": sum(b >= settings.GATE_MIN_VECTOR_SCORE for b in best_out)}}}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
