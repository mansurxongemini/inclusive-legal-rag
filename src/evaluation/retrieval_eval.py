"""
Retrieval-quality evaluation against a golden set that was written from the *real* corpus.

It runs the same pipeline as production (`retrieve_contexts`, gate included) but stops before text
generation, so it is cheap, deterministic and independent of the LLM. Reported:

  hit@k       a correct article is among the first k contexts
  MRR         reciprocal rank of the first correct article (over the final contexts)
  recall@k    share of the expected articles found in the first k contexts
  gate        in-scope questions wrongly refused / out-of-scope questions correctly refused

Dataset item:
  {"id", "question", "language", "expected_ids": [...], "out_of_scope": false, "category", "group", "note"}
  expected_ids are alternatives: retrieving ANY of them answers the question (a question can legitimately be
  answered by the act itself or by the implementing regulation). "expected_law_ids" accepts any unit of an act.
"""
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from src.clients.openrouter import OpenRouterClient
from src.nlp.query_analyzer import QueryAnalyzer
from src.retrieval.pipeline import retrieve_contexts
from src.storage.hybrid_store import HybridStore


@dataclass
class ItemResult:
    id: str
    question: str
    language: str
    out_of_scope: bool
    expected_ids: List[str]
    returned_ids: List[str]
    first_hit_rank: Optional[int]
    refused: bool
    gate_reason: str
    best_vector_score: Optional[float]
    latency_ms: float
    pool_rank: Optional[int] = None          # rank of the first correct article before reranking
    top_rerank_score: Optional[float] = None
    category: str = ""


@dataclass
class EvalReport:
    total: int = 0
    in_scope: int = 0
    out_of_scope: int = 0
    hit_at_1: float = 0.0
    hit_at_3: float = 0.0
    hit_at_5: float = 0.0
    mrr: float = 0.0
    recall_at_5: float = 0.0
    pool_hit_at_10: float = 0.0
    pool_hit_at_30: float = 0.0
    false_refusal_rate: float = 0.0
    correct_refusal_rate: float = 0.0
    avg_latency_ms: float = 0.0
    by_language: Dict[str, Dict[str, float]] = field(default_factory=dict)
    failures: List[dict] = field(default_factory=list)
    items: List[ItemResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["items"] = [asdict(i) for i in self.items]
        return d


class RetrievalEvaluator:
    def __init__(
        self,
        store: HybridStore,
        client: Optional[OpenRouterClient] = None,
        apply_gate: bool = True,
        use_reranker: bool = True,
    ):
        self.store = store
        self.client = client or OpenRouterClient()
        self.apply_gate = apply_gate
        self.use_reranker = use_reranker

    async def run_item(self, item: dict, top_n: int = 8) -> ItemResult:
        t0 = time.perf_counter()
        analysis = QueryAnalyzer.analyze(item["question"], user_language=item.get("language"))
        res = await retrieve_contexts(
            analysis=analysis,
            store=self.store,
            client=self.client,
            top_k=30,
            max_extra=4,
            rerank_top_n=top_n,
            category=item.get("category"),
            apply_gate=self.apply_gate,
            use_reranker=self.use_reranker,
        )
        returned = [c.article.canonical_id for c in res.contexts]
        expected = item.get("expected_ids", [])
        laws = item.get("expected_law_ids", [])
        is_hit = lambda cid: cid in expected or any(cid.startswith(l + "_") for l in laws)  # noqa: E731
        rank = next((i + 1 for i, cid in enumerate(returned) if is_hit(cid)), None)
        # when the gate refused, judge ranking on the pre-gate candidates so the two effects stay separable
        if not returned and res.candidates:
            pool = [c.canonical_id for c in res.candidates]
            rank = next((i + 1 for i, cid in enumerate(pool) if is_hit(cid)), None)
            returned = pool[:top_n]
        pool_ids = [c.canonical_id for c in res.candidates]
        pool_rank = next((i + 1 for i, cid in enumerate(pool_ids) if is_hit(cid)), None)
        rr = [c.rerank_score for c in res.contexts if c.rerank_score is not None]
        vec = [c.vector_score for c in res.candidates if c.vector_score is not None]
        return ItemResult(
            id=item["id"], question=item["question"], language=analysis.detected_language,
            out_of_scope=bool(item.get("out_of_scope")), expected_ids=expected, returned_ids=returned,
            first_hit_rank=rank,
            refused=bool(res.decision and not res.decision.answerable),
            gate_reason=res.decision.reason if res.decision else "n/a",
            best_vector_score=round(max(vec), 3) if vec else None,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            category=item.get("category", "") or "",
            pool_rank=pool_rank,
            top_rerank_score=round(max(rr), 3) if rr else None,
        )

    async def evaluate(self, dataset_path: str) -> EvalReport:
        items = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
        results = [await self.run_item(i) for i in items]
        return self.summarize(results)

    @staticmethod
    def summarize(results: List[ItemResult]) -> EvalReport:
        rep = EvalReport(items=results, total=len(results))
        ins = [r for r in results if not r.out_of_scope]
        outs = [r for r in results if r.out_of_scope]
        rep.in_scope, rep.out_of_scope = len(ins), len(outs)

        def frac(xs, pred) -> float:
            return round(sum(1 for x in xs if pred(x)) / len(xs), 4) if xs else 0.0

        rep.hit_at_1 = frac(ins, lambda r: r.first_hit_rank == 1)
        rep.hit_at_3 = frac(ins, lambda r: r.first_hit_rank is not None and r.first_hit_rank <= 3)
        rep.hit_at_5 = frac(ins, lambda r: r.first_hit_rank is not None and r.first_hit_rank <= 5)
        rep.mrr = round(sum(1.0 / r.first_hit_rank for r in ins if r.first_hit_rank) / len(ins), 4) if ins else 0.0
        rep.recall_at_5 = rep.hit_at_5
        rep.pool_hit_at_10 = frac(ins, lambda r: r.pool_rank is not None and r.pool_rank <= 10)
        rep.pool_hit_at_30 = frac(ins, lambda r: r.pool_rank is not None and r.pool_rank <= 30)
        rep.false_refusal_rate = frac(ins, lambda r: r.refused)
        rep.correct_refusal_rate = frac(outs, lambda r: r.refused)
        rep.avg_latency_ms = round(sum(r.latency_ms for r in results) / len(results), 1) if results else 0.0

        langs = sorted({r.language for r in ins})
        for lg in langs:
            sub = [r for r in ins if r.language == lg]
            rep.by_language[lg] = {
                "n": len(sub),
                "hit@3": frac(sub, lambda r: r.first_hit_rank is not None and r.first_hit_rank <= 3),
                "mrr": round(sum(1.0 / r.first_hit_rank for r in sub if r.first_hit_rank) / len(sub), 4),
            }
        rep.failures = [
            {"id": r.id, "question": r.question, "expected": r.expected_ids, "returned": r.returned_ids[:5],
             "refused": r.refused, "gate": r.gate_reason, "vector": r.best_vector_score}
            for r in ins if r.first_hit_rank is None or r.first_hit_rank > 5 or r.refused
        ] + [
            {"id": r.id, "question": r.question, "expected": [], "returned": r.returned_ids[:3],
             "refused": r.refused, "gate": r.gate_reason, "vector": r.best_vector_score}
            for r in outs if not r.refused
        ]
        return rep
