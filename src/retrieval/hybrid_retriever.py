import logging
from typing import Dict, List, Optional, Union
from pydantic import BaseModel
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient
from src.nlp.query_analyzer import QueryAnalysis, QueryAnalyzer

logger = logging.getLogger(__name__)


class ScoredArticle(BaseModel):
    canonical_id: str
    rrf_score: float
    bm25_rank: Optional[int] = None
    vector_rank: Optional[int] = None
    bm25_score: Optional[float] = None
    vector_score: Optional[float] = None
    source_tag: str = "primary"  # primary | expanded_ref | superseded_replacement


class HybridRetriever:
    """
    Hybrid retriever merging BM25 and dense vector similarity using Reciprocal Rank Fusion (RRF).
    """

    def __init__(self, store: HybridStore, client: Optional[OpenRouterClient] = None):
        self.store = store
        self.client = client or OpenRouterClient()

    def _lookup_direct_article(self, law_id: str, article_number: str) -> Optional[str]:
        """Resolves direct canonical ID for explicit law_id and article_number mention."""
        import re
        import sqlite3
        num_match = re.search(r"(\d+(?:-\d+)?)", article_number)
        if not num_match:
            return None
        num_part = num_match.group(1)
        norm_num = num_part.replace("-", "_")
        
        try:
            with sqlite3.connect(self.store.fts_store.db_path) as conn:
                c = conn.cursor()
                for cid in [f"{law_id}_art_{norm_num}", f"{law_id}_art_{num_part}"]:
                    c.execute("SELECT canonical_id FROM articles_metadata WHERE canonical_id = ?", (cid,))
                    row = c.fetchone()
                    if row:
                        return row[0]
                
                c.execute("""
                    SELECT canonical_id FROM articles_metadata 
                    WHERE json_extract(json_data, '$.metadata.law_id') LIKE ? 
                      AND json_extract(json_data, '$.metadata.article_number') LIKE ?
                    LIMIT 1
                """, (f"{law_id}%", f"%{num_part}%"))
                row = c.fetchone()
                return row[0] if row else None
        except Exception:
            return None

    async def retrieve(
        self,
        query_or_analysis: Union[str, QueryAnalysis],
        top_k: int = 20,
        rrf_k: int = 60,
    ) -> List[ScoredArticle]:
        """
        Retrieves top_k articles using BM25 + Vector similarity fused with RRF.
        Accepts either a raw query string or a pre-computed QueryAnalysis.
        """
        if isinstance(query_or_analysis, str):
            analysis = QueryAnalyzer.analyze(query_or_analysis)
        else:
            analysis = query_or_analysis

        language = analysis.detected_language
        query_text = analysis.normalized_query

        # Check direct article resolution
        direct_cid = None
        if analysis.target_law_id and analysis.target_article_number:
            direct_cid = self._lookup_direct_article(analysis.target_law_id, analysis.target_article_number)

        from src.nlp.query_decomposer import LegalQueryDecomposer

        # 1. Multi-Aspect Query Decomposition and Statutory Synonym Expansion
        subqueries = LegalQueryDecomposer.decompose(query_text)

        # 2. Multi-Aspect Full-Text Search (BM25)
        bm25_rrf_scores: Dict[str, float] = {}
        bm25_best_ranks: Dict[str, int] = {}
        bm25_best_scores: Dict[str, float] = {}

        for sq_idx, sq in enumerate(subqueries):
            sq_weight = 1.0 if sq_idx == 0 else 0.85
            matches = self.store.fts_store.bm25_search(
                query=sq.enriched_query,
                language=language,
                top_k=top_k
            )
            for rank, m in enumerate(matches, start=1):
                cid = m["canonical_id"]
                score_contrib = sq_weight * (1.0 / (rrf_k + rank))
                bm25_rrf_scores[cid] = bm25_rrf_scores.get(cid, 0.0) + score_contrib
                if cid not in bm25_best_ranks or rank < bm25_best_ranks[cid]:
                    bm25_best_ranks[cid] = rank
                    bm25_best_scores[cid] = m["score"]

        # 3. Vector search (BGE-M3 dense) across primary query and key sub-aspects
        embed_texts = [sq.query_text for sq in subqueries[:2]]
        query_vectors = await self.client.get_embeddings(embed_texts)

        vec_rrf_scores: Dict[str, float] = {}
        vec_best_ranks: Dict[str, int] = {}
        vec_best_scores: Dict[str, float] = {}

        for v_idx, q_vec in enumerate(query_vectors):
            v_weight = 1.0 if v_idx == 0 else 0.80
            matches = self.store.vector_store.search_vector(
                query_vector=q_vec,
                top_k=top_k,
                language=language
            )
            for rank, m in enumerate(matches, start=1):
                cid = m["canonical_id"]
                score_contrib = v_weight * (1.0 / (rrf_k + rank))
                vec_rrf_scores[cid] = vec_rrf_scores.get(cid, 0.0) + score_contrib
                if cid not in vec_best_ranks or rank < vec_best_ranks[cid]:
                    vec_best_ranks[cid] = rank
                    vec_best_scores[cid] = m["score"]

        # 4. Global Fusion (Combined BM25 + Vector RRF across all aspects)
        all_ids = set(bm25_rrf_scores.keys()).union(set(vec_rrf_scores.keys()))
        if direct_cid:
            all_ids.add(direct_cid)

        # 5. Batch fetch articles for metadata matching and boosts
        articles_map = self.store.get_articles_batch(list(all_ids))

        scored_articles: List[ScoredArticle] = []

        for cid in all_ids:
            score = bm25_rrf_scores.get(cid, 0.0) + vec_rrf_scores.get(cid, 0.0)
            r_bm25 = bm25_best_ranks.get(cid)
            r_vec = vec_best_ranks.get(cid)


            # Direct match bonus
            if direct_cid and cid == direct_cid:
                score += 0.50

            # Boost if query explicitly mentioned the article or law number
            article = articles_map.get(cid)
            if article:
                if analysis.target_article_number and analysis.target_article_number.lower() in article.metadata.article_number.lower():
                    score += 0.05
                if analysis.target_law_number and analysis.target_law_number.lower() in article.metadata.law_number.lower():
                    score += 0.03
                if analysis.target_law_id and article.metadata.law_id:
                    art_law_id = article.metadata.law_id.lower()
                    tgt = analysis.target_law_id.lower()
                    if art_law_id == tgt or art_law_id.startswith(tgt) or (tgt == "fuqarolik_code" and "fuqarolik" in art_law_id):
                        score += 0.20
                
                # Disability type priority boost
                if analysis.extracted_disability_types and analysis.extracted_disability_types != ["general"]:
                    for dis_type in analysis.extracted_disability_types:
                        if dis_type in article.metadata.disability_types:
                            score += 0.02
                            break



            source_tag = "direct_match" if (direct_cid and cid == direct_cid) else "primary"
            scored_articles.append(ScoredArticle(
                canonical_id=cid,
                rrf_score=score,
                bm25_rank=r_bm25,
                vector_rank=r_vec,
                bm25_score=bm25_best_scores.get(cid),
                vector_score=vec_best_scores.get(cid),
                source_tag=source_tag,
            ))

        # Sort descending by RRF score
        scored_articles.sort(key=lambda x: x.rrf_score, reverse=True)
        return scored_articles[:top_k]
