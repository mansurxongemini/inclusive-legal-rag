import pytest
from src.storage.hybrid_store import HybridStore
from src.evaluation.runner import EvalRunner
from src.clients.openrouter import OpenRouterClient


@pytest.mark.asyncio
async def test_golden_dataset_regression_gate():
    store = HybridStore()
    client = OpenRouterClient()
    runner = EvalRunner(store, client=client)

    report = await runner.evaluate_dataset("data/golden_dataset/golden_eval_set.json")

    assert report.total_questions >= 20
    assert report.correct_refusal_rate >= 0.85, f"Refusal rate too low: {report.correct_refusal_rate}"
    assert report.overall_faithfulness_rate >= 0.90, f"Faithfulness rate too low: {report.overall_faithfulness_rate}"
    assert report.mean_citation_precision >= 0.70, f"Citation precision too low: {report.mean_citation_precision}"
    assert report.mean_citation_recall >= 0.75, f"Citation recall too low: {report.mean_citation_recall}"
    assert report.regression_gate_passed is True
