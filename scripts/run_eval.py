#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage.hybrid_store import HybridStore
from src.evaluation.runner import EvalRunner
from src.clients.openrouter import OpenRouterClient


async def main():
    print("=" * 70)
    print("  UZBEKISTAN LEGAL RAG — GOLDEN DATASET EVALUATION HARNESS")
    print("=" * 70)

    store = HybridStore()
    client = OpenRouterClient()

    # Ensure store is seeded
    if store.count() == 0:
        pilot_file = "data/pilot_laws/law_disability_2020.json"
        print(f"[*] Seeding store with {pilot_file}...")
        await store.seed_from_file(pilot_file, client=client)

    runner = EvalRunner(store, client=client)
    dataset_file = "data/golden_dataset/disability_eval_set.json"
    print(f"[*] Running evaluation on {dataset_file}...")

    report = await runner.evaluate_dataset(dataset_file)

    print("\n" + "-" * 70)
    print(f"  Total Questions Evaluated : {report.total_questions}")
    print(f"  In-Scope Questions        : {report.in_scope_count}")
    print(f"  Out-of-Scope Questions    : {report.out_of_scope_count}")
    print(f"  Mean Citation Precision   : {report.mean_citation_precision * 100:.2f}%")
    print(f"  Mean Citation Recall      : {report.mean_citation_recall * 100:.2f}%")
    print(f"  Mean Citation F1-Score    : {report.mean_citation_f1 * 100:.2f}%")
    print(f"  Correct Refusal Rate      : {report.correct_refusal_rate * 100:.2f}%")
    print(f"  Faithfulness Rate         : {report.overall_faithfulness_rate * 100:.2f}%")
    print(f"  Average Query Latency     : {report.avg_latency_ms:.2f} ms")
    print("-" * 70)

    if report.regression_gate_passed:
        print("\n>>> [PASSED] ALL REGRESSION GATE QUALITY CRITERIA MET! <<<")
        sys.exit(0)
    else:
        print("\n>>> [FAILED] REGRESSION GATE CRITERIA FAILED! <<<")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
