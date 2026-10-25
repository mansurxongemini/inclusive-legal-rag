import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Union
from pydantic import BaseModel
from src.config import settings
from src.storage.hybrid_store import HybridStore
from src.storage.sqlite_utils import connect as sqlite_connect
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
    vector_chunk: Optional[Tuple[str, int]] = None  # (language, chunk_index) of the best vector hit of the article
    source_tag: str = "primary"  # primary | expanded_ref | superseded_replacement


def lift_leaders(scored: List["ScoredArticle"], leaders: set, anchor_position: int) -> None:
    """
    Rank fusion drowns a unit that one list puts first and the other lists do not know (a Tax Code paragraph found by
    words only). Such a unit is lifted to the anchor position, inside the window that Jev reads, and left to Jev to judge.
    `scored` must be sorted by rrf_score; it is re-sorted in place.
    """
    if len(scored) <= anchor_position:
        return
    anchor = scored[anchor_position - 1].rrf_score
    for sa in scored[anchor_position:]:
        if sa.canonical_id in leaders:
            sa.rrf_score = anchor - 1e-6
    scored.sort(key=lambda x: x.rrf_score, reverse=True)


class HybridRetriever:
    """
    Hybrid retriever merging BM25 and dense vector similarity using Reciprocal Rank Fusion (RRF).
    """

    def __init__(self, store: HybridStore, client: Optional[OpenRouterClient] = None):
        self.store = store
        self.client = client or OpenRouterClient()

    @staticmethod
    async def _call(fn, *args, **kwargs):
        """Runs a blocking store call in a worker thread so the event loop keeps serving requests."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _lookup_direct_article(self, law_id: str, article_number: str) -> Optional[str]:
        """Resolves direct canonical ID for explicit law_id and article_number mention."""
        import re
        num_match = re.search(r"(\d+(?:-\d+)?)", article_number)
        if not num_match:
            return None
        num_part = num_match.group(1)
        norm_num = num_part.replace("-", "_")

        try:
            with sqlite_connect(self.store.fts_store.db_path) as conn:
                c = conn.cursor()
                for cid in [f"{law_id}_art_{norm_num}", f"{law_id}_art_{num_part}"]:
                    c.execute("SELECT canonical_id FROM articles_metadata WHERE canonical_id = ?", (cid,))
                    row = c.fetchone()
                    if row:
                        return row[0]

                # LIKE '%5%' also matches 15, 25, 5-1 ...; accept only an exact article-number match so a
                # wrong article is never promoted to a "direct match" (score +0.5, forced to the top).
                c.execute("""
                    SELECT canonical_id, json_extract(json_data, '$.metadata.article_number')
                    FROM articles_metadata
                    WHERE json_extract(json_data, '$.metadata.law_id') LIKE ?
                      AND json_extract(json_data, '$.metadata.article_number') LIKE ?
                    LIMIT 200
                """, (f"{law_id}%", f"%{num_part}%"))
                for cid, art_no in c.fetchall():
                    m = re.search(r"(\d+(?:-\d+)?)", art_no or "")
                    if m and m.group(1) == num_part:
                        return cid
                return None
        except Exception:
            return None

    async def retrieve(
        self,
        query_or_analysis: Union[str, QueryAnalysis],
        top_k: int = 20,
        rrf_k: int = 60,
        precomputed_query_vector: Optional[List[float]] = None,
        use_vector: bool = True,
    ) -> List[ScoredArticle]:
        """
        Retrieves top_k articles using BM25 + Vector similarity fused with RRF.
        Accepts either a raw query string or a pre-computed QueryAnalysis.
        Supports reusing precomputed_query_vector to prevent redundant embedding network roundtrips.
        """
        if isinstance(query_or_analysis, str):
            analysis = QueryAnalyzer.analyze(query_or_analysis)
        else:
            analysis = query_or_analysis

        language = analysis.detected_language
        query_text = analysis.normalized_query

        # Check direct article resolution (only for concise lookup queries, not complex multi-paragraph case studies)
        direct_cid = None
        is_concise_lookup = len(query_text.split()) <= 25
        if is_concise_lookup and analysis.target_law_id and analysis.target_article_number:
            direct_cid = self._lookup_direct_article(analysis.target_law_id, analysis.target_article_number)

        from src.nlp.query_decomposer import LegalQueryDecomposer

        # 1. Multi-Aspect Query Decomposition and Statutory Synonym Expansion
        subqueries = LegalQueryDecomposer.decompose(query_text)

        # 2. Multi-Aspect Full-Text Search (BM25)
        bm25_rrf_scores: Dict[str, float] = {}
        bm25_best_ranks: Dict[str, int] = {}
        bm25_best_scores: Dict[str, float] = {}
        leaders: set = set()          # units at the very top of any single list (see LIST_LEADERS)

        # SQLite and LanceDB calls block: run them in worker threads so that one slow search does not stall every other
        # request served by the event loop, and let the sub-queries search in parallel.
        bm25_matches = await asyncio.gather(*(
            self._call(self.store.fts_store.bm25_search, query=sq.enriched_query, language=language, top_k=top_k)
            for sq in subqueries
        ))
        for sq_idx, matches in enumerate(bm25_matches):
            sq_weight = 1.0 if sq_idx == 0 else 0.85
            for rank, m in enumerate(matches, start=1):
                cid = m["canonical_id"]
                if rank <= settings.LIST_LEADERS:
                    leaders.add(cid)
                score_contrib = sq_weight * (1.0 / (rrf_k + rank))
                bm25_rrf_scores[cid] = bm25_rrf_scores.get(cid, 0.0) + score_contrib
                if cid not in bm25_best_ranks or rank < bm25_best_ranks[cid]:
                    bm25_best_ranks[cid] = rank
                    bm25_best_scores[cid] = m["score"]

        # 3. Vector search (dense, EMBEDDING_MODEL) across primary query and key sub-aspects.
        # If the embedding service is unavailable the request degrades to BM25-only instead of failing.
        query_vectors: List[List[float]] = []
        mismatch = getattr(self.store, "embedding_mismatch", lambda: "")()
        if use_vector and mismatch:
            # vectors of another model would return nonsense with full confidence: full-text search only
            logger.error(f"Dense retrieval off: {mismatch}")
            use_vector = False
        if use_vector:
            # a short question's domain sub-query carries the very same text, so the dense side counts 1.8 times against the
            # full-text side: that is part of the measured ranking (embedding each distinct text once measured hit@1 -3.5)
            embed_texts = [sq.query_text for sq in subqueries[:2]]
            if precomputed_query_vector is not None:
                query_vectors = [precomputed_query_vector]
            try:
                if precomputed_query_vector is not None:
                    if len(embed_texts) > 1:
                        query_vectors += await self.client.get_query_embeddings(embed_texts[1:])
                elif embed_texts:
                    query_vectors = await self.client.get_query_embeddings(embed_texts)
            except Exception as e:
                logger.warning(f"Dense retrieval unavailable, falling back to BM25-only: {e}")

        vec_rrf_scores: Dict[str, float] = {}
        vec_best_ranks: Dict[str, int] = {}
        vec_best_scores: Dict[str, float] = {}
        vec_best_chunks: Dict[str, Tuple[str, int]] = {}

        vector_results = await asyncio.gather(*(
            self._call(self.store.vector_store.search_vector, query_vector=q_vec, top_k=top_k, language=language)
            for q_vec in query_vectors
        ), return_exceptions=True)
        for v_idx, matches in enumerate(vector_results):
            v_weight = 1.0 if v_idx == 0 else 0.80
            if isinstance(matches, Exception):
                logger.warning(f"Vector search failed, skipping dense results: {matches}")
                continue
            for rank, m in enumerate(matches, start=1):
                cid = m["canonical_id"]
                if rank <= settings.LIST_LEADERS:
                    leaders.add(cid)
                score_contrib = v_weight * (1.0 / (rrf_k + rank))
                vec_rrf_scores[cid] = vec_rrf_scores.get(cid, 0.0) + score_contrib
                if cid not in vec_best_ranks or rank < vec_best_ranks[cid]:
                    vec_best_ranks[cid] = rank
                    vec_best_scores[cid] = m["score"]
                    if m.get("chunk_index") is not None and m.get("language"):
                        vec_best_chunks[cid] = (m["language"], m["chunk_index"])
                    else:
                        vec_best_chunks.pop(cid, None)

        # 4. Global Fusion (Combined BM25 + Vector RRF across all aspects)
        all_ids = set(bm25_rrf_scores.keys()).union(set(vec_rrf_scores.keys()))
        if direct_cid:
            all_ids.add(direct_cid)

        # 5. Batch fetch articles for metadata matching and boosts
        articles_map = await self._call(self.store.get_articles_batch, list(all_ids))

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

                # State organ and legal act hierarchy weighting (Constitution > Code > PF > Agency > VMQ > Ministry > Hokimiyat)
                try:
                    from src.retrieval.hierarchy import StateOrganHierarchy
                    law_t = article.metadata.law_title.get(language, "") or article.metadata.law_title.get("uz", "")
                    h_boost = StateOrganHierarchy.calculate_hierarchy_boost(
                        law_title=law_t,
                        law_number=article.metadata.law_number,
                        category=article.metadata.category or "",
                        promulgation_date=article.metadata.promulgation_date,
                        source_type=getattr(article.metadata, "source_type", "lex") or "lex",
                    )
                    score += (h_boost * 0.04)
                except Exception:
                    pass



            source_tag = "direct_match" if (direct_cid and cid == direct_cid) else "primary"
            scored_articles.append(ScoredArticle(
                canonical_id=cid,
                rrf_score=score,
                bm25_rank=r_bm25,
                vector_rank=r_vec,
                bm25_score=bm25_best_scores.get(cid),
                vector_score=vec_best_scores.get(cid),
                vector_chunk=vec_best_chunks.get(cid),
                source_tag=source_tag,
            ))

        # Sort descending by RRF score
        scored_articles.sort(key=lambda x: x.rrf_score, reverse=True)
        if leaders and settings.LIST_LEADERS > 0:
            lift_leaders(scored_articles, leaders, settings.LEADER_ANCHOR_POSITION)
        return scored_articles[:top_k]
