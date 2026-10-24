from typing import List
from pydantic import BaseModel


class SingleEvalResult(BaseModel):
    id: str
    question: str
    language: str
    is_out_of_scope: bool
    predicted_is_refusal: bool
    expected_canonical_ids: List[str]
    predicted_canonical_ids: List[str]
    citation_precision: float
    citation_recall: float
    citation_f1: float
    faithfulness: float
    correct_refusal: bool
    latency_ms: float


class EvalSummaryReport(BaseModel):
    total_questions: int
    in_scope_count: int
    out_of_scope_count: int
    mean_citation_precision: float
    mean_citation_recall: float
    mean_citation_f1: float
    correct_refusal_rate: float
    overall_faithfulness_rate: float
    avg_latency_ms: float
    regression_gate_passed: bool


# Ids that may legitimately substitute for each other (e.g. a consolidated and an original edition).
# Keep this empty unless two ids are verifiably the same provision: clusters between different articles only
# inflate the score. (The previous list mapped unrelated article numbers to each other.)
EQUIVALENCE_CLUSTERS: list = []

CANONICAL_EQUIVALENTS = {}
for cluster in EQUIVALENCE_CLUSTERS:
    for item in cluster:
        CANONICAL_EQUIVALENTS[item] = cluster


def compute_citation_scores(pred: List[str], exp: List[str]):
    s_pred = set(pred)
    s_exp = set(exp)

    if not s_exp:
        # Out of scope query
        precision = 1.0 if not s_pred else 0.0
        recall = 1.0
        f1 = 1.0 if not s_pred else 0.0
        return precision, recall, f1

    if not s_pred:
        return 0.0, 0.0, 0.0

    covered_exp = sum(
        1 for e in exp
        if (e in s_pred or any(eq in s_pred for eq in CANONICAL_EQUIVALENTS.get(e, set())))
    )
    recall = covered_exp / len(exp)

    valid_pred = sum(
        1 for p in pred
        if (p in s_exp or any(eq in s_exp for eq in CANONICAL_EQUIVALENTS.get(p, set())))
    )
    precision = valid_pred / len(pred)

    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1
