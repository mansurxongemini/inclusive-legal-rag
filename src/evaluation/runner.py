import json
import logging
import time
from pathlib import Path
from typing import List, Optional
from src.storage.hybrid_store import HybridStore
from src.nlp.query_analyzer import QueryAnalyzer
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.expansion import expand_cross_references
from src.retrieval.status_filter import apply_status_and_amendment_filter
from src.retrieval.reranker import Reranker
from src.generation.generator import AnswerGenerator
from src.clients.openrouter import OpenRouterClient
from src.evaluation.metrics import (
    SingleEvalResult,
    EvalSummaryReport,
    compute_citation_scores,
)

logger = logging.getLogger(__name__)


class EvalRunner:
    """Evaluates the Legal RAG platform against the golden dataset."""

    def __init__(self, store: HybridStore, client: Optional[OpenRouterClient] = None):
        self.store = store
        self.client = client or OpenRouterClient()
        self.retriever = HybridRetriever(store, client=self.client)
        self.reranker = Reranker(client=self.client)
        self.generator = AnswerGenerator(client=self.client)

    async def evaluate_dataset(
        self,
        dataset_path: str = "data/golden_dataset/disability_eval_set.json",
        max_questions: Optional[int] = None,
    ) -> EvalSummaryReport:
        path = Path(dataset_path)
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)

        if max_questions:
            items = items[:max_questions]

        results: List[SingleEvalResult] = []
        precisions = []
        recalls = []
        f1s = []
        refusals_correct = []
        faithfulness_scores = []
        latencies = []

        in_scope_count = 0
        out_of_scope_count = 0

        for item in items:
            q_id = item["id"]
            question = item["question"]
            exp_ids = item.get("expected_ids", item.get("expected_canonical_ids", []))
            is_out = item.get("out_of_scope", item.get("is_out_of_scope", False))

            if is_out:
                out_of_scope_count += 1
            else:
                in_scope_count += 1

            start_t = time.perf_counter()

            # 1. Analyze query
            analysis = QueryAnalyzer.analyze(question)
            target_lang = analysis.detected_language

            # 2. Hybrid retrieve (candidate pool sized for 55k+ article scale)
            raw_cands = await self.retriever.retrieve(analysis, top_k=30)

            # 3. Expand 1-hop
            expanded_cands = expand_cross_references(raw_cands, self.store, max_extra=4)

            # 4. Status filter
            filtered_cands, _ = apply_status_and_amendment_filter(expanded_cands, self.store)

            # 5. Rerank
            contexts = await self.reranker.rerank(
                query=analysis.normalized_query,
                language=target_lang,
                candidates=filtered_cands,
                store=self.store,
                top_n=6,
            )


            # 6. Generate answer + validation pass
            gen_res = await self.generator.generate_answer(
                query=question,
                contexts=contexts,
                language=target_lang,
                mode="plain",
            )

            latency_ms = (time.perf_counter() - start_t) * 1000.0
            latencies.append(latency_ms)

            pred_ids = [c.canonical_id for c in gen_res.citations]

            # Compute metrics
            prec, rec, f1 = compute_citation_scores(pred_ids, exp_ids)
            
            if not is_out:
                precisions.append(prec)
                recalls.append(rec)
                f1s.append(f1)

            correct_ref = (gen_res.is_refusal == is_out)
            refusals_correct.append(1.0 if correct_ref else 0.0)

            faithfulness = 1.0 if gen_res.validation_passed else 0.0
            faithfulness_scores.append(faithfulness)

            results.append(SingleEvalResult(
                id=q_id,
                question=question,
                language=target_lang,
                is_out_of_scope=is_out,
                predicted_is_refusal=gen_res.is_refusal,
                expected_canonical_ids=exp_ids,
                predicted_canonical_ids=pred_ids,
                citation_precision=prec,
                citation_recall=rec,
                citation_f1=f1,
                faithfulness=faithfulness,
                correct_refusal=correct_ref,
                latency_ms=latency_ms,
            ))

        mean_p = sum(precisions) / len(precisions) if precisions else 0.0
        mean_r = sum(recalls) / len(recalls) if recalls else 0.0
        mean_f1 = sum(f1s) / len(f1s) if f1s else 0.0
        refusal_rate = sum(refusals_correct) / len(refusals_correct) if refusals_correct else 0.0
        overall_faith = sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else 0.0
        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0

        # Regression gate thresholds
        gate_passed = (
            mean_r >= 0.75 and
            mean_p >= 0.70 and
            refusal_rate >= 0.85 and
            overall_faith >= 0.90
        )

        return EvalSummaryReport(
            total_questions=len(items),
            in_scope_count=in_scope_count,
            out_of_scope_count=out_of_scope_count,
            mean_citation_precision=round(mean_p, 4),
            mean_citation_recall=round(mean_r, 4),
            mean_citation_f1=round(mean_f1, 4),
            correct_refusal_rate=round(refusal_rate, 4),
            overall_faithfulness_rate=round(overall_faith, 4),
            avg_latency_ms=round(avg_lat, 2),
            regression_gate_passed=gate_passed,
        )
