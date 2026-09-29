from typing import List, Set
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


EQUIVALENCE_CLUSTERS = [
    {"law_labor_code_art_425", "mehnat_code_art_427", "mehnat_code_art_425"},
    {"law_disability_2020_art_15", "law_o_rq_641_art_35", "law_o_rq_641_art_36"},
    {"law_disability_2020_art_22", "law_o_rq_641_art_23", "law_o_rq_641_art_22"},
    {"law_disability_2020_art_24", "law_o_rq_641_art_25", "law_o_rq_641_art_24"},
    {"law_disability_2020_art_28", "law_o_rq_641_art_40"},
    {"law_disability_2020_art_36", "law_o_rq_641_art_43"},
    {"law_disability_2020_art_45", "law_o_rq_641_art_37"},
    {"law_disability_2020_art_5", "law_o_rq_641_art_4"},
    {"law_disability_2020_art_3", "law_o_rq_641_art_3"},
]

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
