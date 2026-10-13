import json
import logging
import re
from typing import Dict, List, Optional
from pydantic import BaseModel
from src.schema.canonical import CanonicalArticle
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient
from src.retrieval.hybrid_retriever import ScoredArticle
from src.retrieval.jev_ranker import JevRanker
from src.config import settings

logger = logging.getLogger(__name__)


MAX_RERANK_UNITS = 40
MAX_RERANK_DOCS = 100
WINDOW_SIZE = 700
WINDOW_OVERLAP = 150
MAX_WINDOWS_PER_UNIT = 8


def split_windows(
    text: str,
    size: int = WINDOW_SIZE,
    overlap: int = WINDOW_OVERLAP,
    max_windows: int = MAX_WINDOWS_PER_UNIT,
) -> List[str]:
    """
    Splits text into sliding windows of up to `size` characters stepping by `size - overlap`.
    Ends each window at the last whitespace in the final 80 characters of the window when one exists.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    step = size - overlap
    if step <= 0:
        step = size

    windows: List[str] = []
    start = 0
    text_len = len(text)

    while start < text_len and len(windows) < max_windows:
        end = min(start + size, text_len)
        if end < text_len:
            # End window at the last whitespace inside the final 80 chars
            search_start = max(start, end - 80)
            last_space = -1
            for i in range(end - 1, search_start - 1, -1):
                if text[i].isspace():
                    last_space = i
                    break
            if last_space != -1:
                end = last_space

        win = text[start:end].strip()
        if win:
            windows.append(win)

        if end >= text_len:
            break

        # Step forward
        start += step
        if start >= text_len:
            break

        # Skip leading whitespace
        while start < text_len and text[start].isspace():
            start += 1
        if start >= text_len:
            break

        # If start is in the middle of a word, adjust to word boundary
        if start > 0 and not text[start - 1].isspace():
            space_before = -1
            for i in range(start - 1, max(0, start - overlap) - 1, -1):
                if text[i].isspace():
                    space_before = i
                    break
            if space_before != -1:
                start = space_before + 1
            else:
                space_after = -1
                for i in range(start, text_len):
                    if text[i].isspace():
                        space_after = i
                        break
                if space_after != -1:
                    start = space_after + 1
                    while start < text_len and text[start].isspace():
                        start += 1

    return windows


class RetrievedArticleContext(BaseModel):
    article: CanonicalArticle
    final_score: float
    source_tag: str
    is_superseded: bool = False
    superseded_by: Optional[str] = None
    rerank_score: Optional[float] = None     # cross-encoder relevance (0..1) when a reranker model scored it


class Reranker:
    """
    Reranks candidate articles down to top-N using an LLM scoring prompt or fast hybrid fallback.
    """

    def __init__(self, client: Optional[OpenRouterClient] = None):
        self.client = client or OpenRouterClient()
        self.last_provider: str = "none"
        self.last_answerable: Optional[float] = None

    async def rerank(
        self,
        query: str,
        language: str,
        candidates: List[ScoredArticle],
        store: HybridStore,
        top_n: int = 5,
        use_model: bool = True,
    ) -> List[RetrievedArticleContext]:
        self.last_provider = "none"
        self.last_answerable = None

        if not candidates:
            return []

        # 1. Batch load articles
        cids = [c.canonical_id for c in candidates]
        articles_map = store.get_articles_batch(cids)

        article_contexts: List[RetrievedArticleContext] = []
        for c in candidates:
            art = articles_map.get(c.canonical_id)
            if art:
                article_contexts.append(RetrievedArticleContext(
                    article=art,
                    final_score=c.rrf_score,
                    source_tag=c.source_tag,
                    is_superseded=(art.metadata.status.value in ("repealed", "amended")),
                    superseded_by=art.metadata.superseded_by,
                ))

        if len(article_contexts) <= top_n or not use_model:
            self.last_provider = "rrf"
            article_contexts.sort(key=lambda x: x.final_score, reverse=True)
            return article_contexts[:top_n]

        # Jev reranker path
        if settings.RERANK_PROVIDER == "jev" and not getattr(self.client, "is_mock", False):
            # (Capping the units one act may send here was tried: it lowered MRR on both eval sets, so RRF order is kept.)
            subset = article_contexts[:settings.JEV_RERANK_UNITS]
            try:
                result = await JevRanker(self.client).rank(query, subset)
            except Exception as e:  # an unexpected response must not fail the request: Cohere takes over
                logger.warning(f"Jev rerank failed: {e}")
                result = None
            if result:
                for n, ctx in enumerate(subset):
                    ctx.rerank_score = result.probabilities[n]
                    ctx.final_score = (3.0 if ctx.source_tag == "direct_match" else 0.0) + result.probabilities[n]
                ranked = [subset[n] for n in result.order]
                direct = [c for c in subset if c.source_tag == "direct_match"]
                non_direct = [c for c in ranked if c.source_tag != "direct_match"]
                ranked = direct + non_direct
                self.last_provider = "jev"
                self.last_answerable = result.answerable
                return ranked[:top_n]
            else:
                logger.warning("Jev rerank unavailable, falling back to Cohere")

        # Use OpenRouter dedicated /rerank endpoint
        try:
            # Evaluate up to MAX_RERANK_UNITS candidates across sliding windows (up to MAX_RERANK_DOCS documents)
            candidate_subset = article_contexts[:MAX_RERANK_UNITS]

            unit_headers: List[str] = []
            unit_windows: List[List[str]] = []
            for ctx in candidate_subset:
                law_t = ctx.article.metadata.law_title.get(language, "") or ctx.article.metadata.law_title.get("uz", "")
                art_num = ctx.article.metadata.article_number
                art_title = ctx.article.get_title(language)
                header = f"{law_t} {art_num} {art_title}."
                unit_headers.append(header)

                body = ctx.article.get_text(language)
                wins = split_windows(body)
                unit_windows.append(wins if wins else [""])

            documents: List[str] = []
            doc_owner: List[int] = []

            # Budget: every unit gets its first window
            for u in range(len(candidate_subset)):
                documents.append(f"{unit_headers[u]} {unit_windows[u][0]}")
                doc_owner.append(u)

            # Fill remaining budget (MAX_RERANK_DOCS - number of units) with further windows in candidate order
            remaining_budget = MAX_RERANK_DOCS - len(documents)
            for u in range(len(candidate_subset)):
                if remaining_budget <= 0:
                    break
                for w in unit_windows[u][1:]:
                    if remaining_budget <= 0:
                        break
                    documents.append(f"{unit_headers[u]} {w}")
                    doc_owner.append(u)
                    remaining_budget -= 1

            rerank_results = await self.client.rerank_documents(
                query=query,
                documents=documents,
                model=settings.RERANK_MODEL,
                top_n=len(documents)
            )

            if rerank_results:
                unit_best_score: Dict[int, float] = {}
                for item in rerank_results:
                    idx = item.get("index")
                    rel_score = float(item.get("relevance_score", 0.0))
                    if idx is not None and 0 <= idx < len(doc_owner):
                        u = doc_owner[idx]
                        if u not in unit_best_score or rel_score > unit_best_score[u]:
                            unit_best_score[u] = rel_score

                reranked_contexts = []
                for u, rel_score in unit_best_score.items():
                    if u < len(candidate_subset):
                        ctx = candidate_subset[u]
                        ctx.rerank_score = rel_score
                        if ctx.source_tag == "direct_match":
                            ctx.final_score = 3.0 + rel_score
                        else:
                            try:
                                from src.retrieval.hierarchy import StateOrganHierarchy
                                law_t = ctx.article.metadata.law_title.get(language, "") or ctx.article.metadata.law_title.get("uz", "")
                                h_boost = StateOrganHierarchy.calculate_hierarchy_boost(
                                    law_title=law_t,
                                    law_number=ctx.article.metadata.law_number,
                                    category=ctx.article.metadata.category or "",
                                    promulgation_date=ctx.article.metadata.promulgation_date
                                )
                            except Exception:
                                h_boost = 0.70

                            # Fusion: cross-encoder relevance (60%), initial RRF (25%), legal-force hierarchy (15%).
                            # (A recency term was tried: it demoted correct 2022-2024 regulations behind newer,
                            # less specific acts and lowered MRR on the golden set, so it is not used.)
                            ctx.final_score = (ctx.final_score * 0.25) + (rel_score * 0.60) + (h_boost * 0.15)
                        reranked_contexts.append(ctx)

                # Intent protection: Ensure direct_match candidates are never dropped
                for ctx in candidate_subset:
                    if ctx.source_tag == "direct_match" and ctx not in reranked_contexts:
                        ctx.final_score = 3.0
                        reranked_contexts.insert(0, ctx)

                if reranked_contexts:
                    reranked_contexts.sort(key=lambda x: x.final_score, reverse=True)
                    self.last_provider = "cohere"
                    return reranked_contexts[:top_n]
        except Exception as e:
            logger.warning(f"Rerank API failed, falling back to RRF: {e}")

        self.last_provider = "rrf"
        article_contexts.sort(key=lambda x: x.final_score, reverse=True)
        return article_contexts[:top_n]
