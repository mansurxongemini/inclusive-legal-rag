"""
Retrieval regression gate on the real corpus fixture (official text of O'RQ-641).

The golden set (data/golden_dataset/disability_eval_set.json) was written from the full corpus; this gate runs
the part of it that the shipped seed can answer and fails when ranking quality drops. The full corpus
evaluation (all acts, live embeddings, relevance gate) is `python scripts/evaluate_retrieval.py`.
"""
import json
from pathlib import Path

import pytest

from src.clients.openrouter import OpenRouterClient
from src.evaluation.retrieval_eval import RetrievalEvaluator
from src.storage.hybrid_store import HybridStore

ROOT = Path(__file__).resolve().parents[1]


def _seed_ids():
    items = json.loads((ROOT / "data" / "pilot_laws" / "law_disability_2020.json").read_text(encoding="utf-8"))
    return {i["canonical_id"] for i in items}


def test_golden_labels_are_grounded_in_the_corpus():
    """Every expected id of the golden set exists in the corpus and contains its evidence phrase. With the built corpus
    (data/sources/built_articles.json, not in git) every item is checked; in a fresh clone the items the shipped seed
    covers are (the test used to skip there)."""
    built = ROOT / "data" / "sources" / "built_articles.json"
    source = built if built.exists() else ROOT / "data" / "pilot_laws" / "law_disability_2020.json"
    arts = {a["canonical_id"]: a for a in json.loads(source.read_text(encoding="utf-8"))}
    norm = lambda s: s.replace("ʻ", "'").replace("ʼ", "'").replace("’", "'").lower()  # noqa: E731
    items = [i for i in json.loads((ROOT / "data" / "golden_dataset" / "disability_eval_set.json").read_text(encoding="utf-8"))
             if not i.get("out_of_scope")]
    if not built.exists():
        items = [i for i in items if i["expected_ids"] and all(e in arts for e in i["expected_ids"])]
        assert len(items) >= 8, "the seed covers too few golden items to check"
    for item in items:
        present = [e for e in item["expected_ids"] if e in arts]
        assert present, f"{item['id']}: none of the expected ids exist"
        assert any(norm(item["evidence"]) in norm(arts[e]["translations"]["uz"]) for e in present), (
            f"{item['id']}: evidence phrase not found in any expected article"
        )


@pytest.mark.asyncio
async def test_retrieval_regression_gate(tmp_path):
    seed_ids = _seed_ids()
    items = json.loads((ROOT / "data" / "golden_dataset" / "disability_eval_set.json").read_text(encoding="utf-8"))
    subset = [
        i for i in items
        if not i.get("out_of_scope") and i["language"] in ("uz", "ru", "en")
        and i["expected_ids"] and all(e in seed_ids for e in i["expected_ids"])
    ]
    assert len(subset) >= 8, "golden subset for the seed shrank"

    store = HybridStore(str(tmp_path / "store"))
    client = OpenRouterClient()
    await store.seed_from_file(str(ROOT / "data" / "pilot_laws" / "law_disability_2020.json"), client=client)

    report = RetrievalEvaluator(store, client=client, apply_gate=False).summarize(
        [await RetrievalEvaluator(store, client=client, apply_gate=False).run_item(i) for i in subset]
    )
    assert report.hit_at_5 >= 0.70, f"hit@5 dropped to {report.hit_at_5}: {report.failures}"
    assert report.mrr >= 0.45, f"MRR dropped to {report.mrr}"
