#!/usr/bin/env python3
"""
Why does a question miss its unit? For stress-set items (or a free question plus --expect ids) it prints the language
handling (normalised query, Uzbek rewrite/translation, sub-questions), the full-text and dense rank of the expected unit
with a wide window (top 300), and the candidate pool order. Read-only.

  python scripts/diagnose_question.py s043 s075
  python scripts/diagnose_question.py --question "..." --expect vmq_62_2022_a9_p_16
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SPEND_SCOPE", "eval")      # evaluation spend is counted apart and never limited by the service budget

from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.nlp.query_analyzer import QueryAnalyzer  # noqa: E402
from src.nlp.query_translator import QueryTranslator  # noqa: E402
from src.retrieval.pipeline import retrieve_contexts  # noqa: E402
from src.storage.fts_store import build_fts_terms  # noqa: E402
from src.storage.hybrid_store import HybridStore  # noqa: E402


async def diagnose(item, store, client, wide: int) -> None:
    question, expected = item["question"], item.get("expected_ids", [])
    analysis = QueryAnalyzer.analyze(question)
    lang = analysis.detected_language
    print(f"\n=== {item.get('id', '-')} [{item.get('difficulty', '')}] lang={lang}/{analysis.detected_script}\nQ: {question}")
    print(f"normalized: {analysis.normalized_query}")
    uz = None
    if lang in ("ru", "en"):
        uz = await QueryTranslator.to_uzbek(analysis.normalized_query, lang, client)
    elif lang == "uz":
        uz = await QueryTranslator.normalize_uzbek(analysis.raw_query, client)
    print(f"uzbek rewrite: {uz}")
    print(f"fts terms: {' '.join(build_fts_terms(uz or analysis.normalized_query))}")
    for cid in expected:
        art = store.get_article(cid)
        if art is None:
            print(f"expected {cid}: NOT IN THE STORE")
            continue
        print(f"expected {cid}: {art.metadata.law_number} {art.metadata.article_number} | ru text: {bool(art.translations.get('ru'))} "
              f"| {len(art.get_text('uz'))} chars\n   {' '.join(art.get_text('uz').split())[:260]}")
        for label, text in (("original", analysis.normalized_query), ("rewrite", uz)):
            if not text:
                continue
            for fts_lang in ("uz", "ru") if lang != "uz" else ("uz",):
                hits = store.fts_store.bm25_search(text, language=fts_lang, top_k=wide)
                ids = [h["canonical_id"] for h in hits]
                print(f"   bm25[{label},{fts_lang}] rank of expected: {ids.index(cid) + 1 if cid in ids else '-'} of {len(ids)}")
        vec = (await client.get_embeddings([analysis.normalized_query] + ([uz] if uz else [])))
        for label, v in zip(("original", "rewrite"), vec):
            hits = store.vector_store.search_vector(v, top_k=wide, language=lang)
            ids = []
            for h in hits:
                if h["canonical_id"] not in ids:
                    ids.append(h["canonical_id"])
            print(f"   dense[{label}] rank of expected: {ids.index(cid) + 1 if cid in ids else '-'} of {len(ids)} units")
    res = await retrieve_contexts(analysis=analysis, store=store, client=client, top_k=25, max_extra=6, rerank_top_n=6)
    pool = [c.canonical_id for c in res.candidates]
    ctx = [c.article.canonical_id for c in res.contexts]
    print(f"pool rank: {[pool.index(e) + 1 if e in pool else '-' for e in expected]}  context rank: "
          f"{[ctx.index(e) + 1 if e in ctx else '-' for e in expected]}  refused: {bool(res.decision and not res.decision.answerable)}")
    print("contexts:", ctx)
    print("signals:", {k: v for k, v in (res.signals or {}).items() if k != 'subquestions'},
          "subquestions:", (res.signals or {}).get("subquestions"))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--dataset", default=str(ROOT / "data" / "golden_dataset" / "stress_eval_200.json"))
    ap.add_argument("--question", default="")
    ap.add_argument("--expect", action="append", default=[])
    ap.add_argument("--wide", type=int, default=300)
    args = ap.parse_args()
    store, client = HybridStore(str(ROOT / "data" / "store")), OpenRouterClient()
    items = []
    if args.question:
        items.append({"id": "adhoc", "question": args.question, "expected_ids": args.expect})
    if args.ids:
        by_id = {i["id"]: i for i in json.loads(Path(args.dataset).read_text(encoding="utf-8"))}
        items += [by_id[i] for i in args.ids]
    for item in items:
        await diagnose(item, store, client, args.wide)
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
