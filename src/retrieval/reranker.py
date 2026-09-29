import json
import logging
import re
from typing import Dict, List, Optional
from pydantic import BaseModel
from src.schema.canonical import CanonicalArticle
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient
from src.retrieval.hybrid_retriever import ScoredArticle
from src.config import settings

logger = logging.getLogger(__name__)


class RetrievedArticleContext(BaseModel):
    article: CanonicalArticle
    final_score: float
    source_tag: str
    is_superseded: bool = False
    superseded_by: Optional[str] = None


class Reranker:
    """
    Reranks candidate articles down to top-N using an LLM scoring prompt or fast hybrid fallback.
    """

    def __init__(self, client: Optional[OpenRouterClient] = None):
        self.client = client or OpenRouterClient()

    async def rerank(
        self,
        query: str,
        language: str,
        candidates: List[ScoredArticle],
        store: HybridStore,
        top_n: int = 5,
    ) -> List[RetrievedArticleContext]:
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

        if len(article_contexts) <= top_n:
            article_contexts.sort(key=lambda x: x.final_score, reverse=True)
            return article_contexts[:top_n]

        # Use OpenRouter dedicated /rerank endpoint
        try:
            # Evaluate up to 32 candidates to ensure comprehensive coverage across multi-aspect questions
            subset_size = min(len(article_contexts), max(top_n * 4, 30))
            candidate_subset = article_contexts[:subset_size]
            documents = [
                f"{ctx.article.metadata.law_title.get(language, '')} {ctx.article.metadata.article_number} {ctx.article.get_title(language)}. {ctx.article.get_text(language)[:800]}"
                for ctx in candidate_subset
            ]


            rerank_results = await self.client.rerank_documents(
                query=query,
                documents=documents,
                model=settings.RERANK_MODEL,
                top_n=top_n
            )

            if rerank_results:
                reranked_contexts = []
                for item in rerank_results:
                    idx = item.get("index")
                    rel_score = float(item.get("relevance_score", 0.0))
                    if idx is not None and idx < len(candidate_subset):
                        ctx = candidate_subset[idx]
                        if ctx.source_tag == "direct_match":
                            ctx.final_score = 2.0 + rel_score
                        else:
                            ctx.final_score = (ctx.final_score * 0.4) + (rel_score * 0.6)
                        reranked_contexts.append(ctx)

                # Intent protection: Ensure direct_match candidates are never dropped
                for ctx in candidate_subset:
                    if ctx.source_tag == "direct_match" and ctx not in reranked_contexts:
                        ctx.final_score = 3.0
                        reranked_contexts.insert(0, ctx)

                if reranked_contexts:
                    reranked_contexts.sort(key=lambda x: x.final_score, reverse=True)
                    return reranked_contexts[:top_n]
        except Exception as e:
            logger.warning(f"Rerank API failed, falling back to RRF: {e}")

        article_contexts.sort(key=lambda x: x.final_score, reverse=True)
        return article_contexts[:top_n]
