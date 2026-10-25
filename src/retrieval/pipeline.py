"""
One retrieval pipeline shared by every query endpoint:

    hybrid retrieval (ru/en questions also through an Uzbek translation: the vectors are Uzbek only) -> (optional category focus) -> cross-reference expansion -> status filter
    -> rerank (Jev with Cohere fallback) -> relevance gate

Returns the contexts to answer from (empty when the evidence is not good enough) plus diagnostics.
"""
import asyncio
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.clients.openrouter import OpenRouterClient
from src.config import settings
from src.nlp.query_analyzer import QueryAnalysis, QueryAnalyzer
from src.nlp.legal_synonyms import LegalSynonymExpander
from src.nlp.query_translator import QueryTranslator
from src.retrieval.expansion import expand_cross_references
from src.retrieval.hybrid_retriever import HybridRetriever, ScoredArticle
from src.retrieval.jev_ranker import JevRanker
from src.retrieval.relevance_gate import GateDecision, RelevanceGate, jev_gate_decision
from src.retrieval.repeal_notices import repeal_notices
from src.retrieval.reranker import Reranker, RetrievedArticleContext
from src.retrieval.status_filter import apply_status_and_amendment_filter
from src.storage.hybrid_store import HybridStore

logger = logging.getLogger(__name__)

CATEGORY_BOOST = 0.03
# Rank constant of the fusion of a long question's hits with its sub-questions' hits: small, so the first hits of
# every list lead the pool whatever their raw scores (with k=60 a unit that is 20th in two lists beats every list's first).
ASPECT_RRF_K = 5


def merge_candidates(lists: List[List[ScoredArticle]], limit: int) -> List[ScoredArticle]:
    """
    Groups candidate lists by canonical_id, aggregating scores and ranks without mutating inputs:
    - rrf_score = sum
    - bm25_rank and vector_rank = min of non-None
    - bm25_score and vector_score = max of non-None; vector_chunk comes from the item with the best vector_score
    - source_tag = 'direct_match' if any tagged so, else the first seen
    - returns sorted by rrf_score desc, cut to limit.
    """
    grouped: Dict[str, List[ScoredArticle]] = {}
    for cand_list in lists:
        for cand in cand_list:
            grouped.setdefault(cand.canonical_id, []).append(cand)

    merged: List[ScoredArticle] = []
    for cid, items in grouped.items():
        total_rrf = sum(item.rrf_score for item in items)

        bm25_ranks = [item.bm25_rank for item in items if item.bm25_rank is not None]
        best_bm25_rank = min(bm25_ranks) if bm25_ranks else None

        vector_ranks = [item.vector_rank for item in items if item.vector_rank is not None]
        best_vector_rank = min(vector_ranks) if vector_ranks else None

        bm25_scores = [item.bm25_score for item in items if item.bm25_score is not None]
        best_bm25_score = max(bm25_scores) if bm25_scores else None

        vector_scores = [item.vector_score for item in items if item.vector_score is not None]
        best_vector_score = max(vector_scores) if vector_scores else None
        with_chunk = [item for item in items if item.vector_chunk is not None and item.vector_score is not None]
        best_vector_chunk = max(with_chunk, key=lambda item: item.vector_score).vector_chunk if with_chunk else None

        if any(item.source_tag == "direct_match" for item in items):
            source_tag = "direct_match"
        else:
            source_tag = items[0].source_tag

        merged.append(
            ScoredArticle(
                canonical_id=cid,
                rrf_score=total_rrf,
                bm25_rank=best_bm25_rank,
                vector_rank=best_vector_rank,
                bm25_score=best_bm25_score,
                vector_score=best_vector_score,
                vector_chunk=best_vector_chunk,
                source_tag=source_tag,
            )
        )

    merged.sort(key=lambda c: c.rrf_score, reverse=True)
    return merged[:limit]


def fuse_aspect_candidates(
    base: List[ScoredArticle], aspect_lists: List[List[ScoredArticle]], limit: int, k: int = ASPECT_RRF_K,
) -> List[ScoredArticle]:
    """
    Fuses the hits of a long question (base) with the hits of each of its legal sub-questions by rank:
    rrf_score = sum over the lists of 1 / (k + rank). Raw scores are not comparable here: the story's own hits are
    summed over the original and the rewritten text and would bury the norms only one sub-question finds (the appeal
    procedure when the story is about a refused application). In a sub-question's list a unit ranks by the better of
    its place and its dense rank: the short question embeds cleanly, while its lexical side is padded with domain
    terms and pulls generic laws ahead of the regulation that answers it. Other fields are merged as in merge_candidates.
    """
    lists = [base] + aspect_lists
    fused: Dict[str, float] = {}
    for n, cand_list in enumerate(lists):
        for rank, cand in enumerate(cand_list, start=1):
            if n:
                rank = min([rank] + [r for r in (cand.vector_rank, cand.bm25_rank) if r is not None])
            fused[cand.canonical_id] = fused.get(cand.canonical_id, 0.0) + 1.0 / (k + rank)
    merged = merge_candidates(lists, limit=len(fused))
    for cand in merged:
        cand.rrf_score = fused[cand.canonical_id]
    merged.sort(key=lambda c: c.rrf_score, reverse=True)
    return merged[:limit]


def _wants_subquestions(analysis: QueryAnalysis) -> bool:
    min_words = settings.QUERY_SUBQUESTIONS_MIN_WORDS
    return min_words > 0 and len(analysis.normalized_query.split()) >= min_words


@dataclass
class RetrievalResult:
    contexts: List[RetrievedArticleContext] = field(default_factory=list)
    candidates: List[ScoredArticle] = field(default_factory=list)
    status_warnings: List[dict] = field(default_factory=list)
    decision: Optional[GateDecision] = None
    signals: Dict[str, object] = field(default_factory=dict)


def _word_overlap(a: str, b: str) -> float:
    norm = lambda t: set(re.findall(r"[a-z0-9']+", re.sub(r"[ʻʼ‘’`]", "'", t.lower())))
    wa, wb = norm(a), norm(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 1.0


def _use_uz_rewrite(rewrite: str, analysis: QueryAnalysis) -> bool:
    """A Cyrillic question is transliterated with its typos kept, so its rewrite is always searched too. A Latin
    question is searched again only when the rewrite changed most of its words (a misspelled question); a clean one
    gains nothing and the extra candidates only blur the ranking."""
    overlap = _word_overlap(rewrite, analysis.normalized_query)
    return overlap < 0.9 if analysis.detected_script == "cyrillic" else overlap < 0.5


def _discard_tasks(tasks: List[asyncio.Task]) -> None:
    """Cancels the helper tasks that a failed (or finished) retrieval left running, e.g. a paid Jev call or an LLM
    rewrite, and marks the error of one that had already failed as seen so that nothing is logged as never retrieved."""
    for task in tasks:
        if not task.done():
            task.cancel()
        elif not task.cancelled():
            task.exception()


async def retrieve_contexts(
    *,
    analysis: QueryAnalysis,
    store: HybridStore,
    client: OpenRouterClient,
    top_k: int = 30,
    max_extra: int = 6,
    rerank_top_n: int = 8,
    query_vector: Optional[List[float]] = None,
    use_vector: bool = True,
    category: Optional[str] = None,
    apply_gate: bool = True,
    use_reranker: bool = True,
    use_llm: bool = True,
) -> RetrievalResult:
    """use_llm=False makes no model call at all (no translation, rewrite, sub-questions, scope or ranking): the fallback
    of retrieve_within when the provider does not answer in time."""
    language = analysis.detected_language
    if not use_llm:
        use_reranker = False
    retriever = HybridRetriever(store, client=client)

    use_jev = settings.RERANK_PROVIDER == "jev" and not client.is_mock and use_reranker
    scope_task: Optional[asyncio.Task] = None
    if use_jev and apply_gate and settings.GATE_JEV_SCOPE_ENABLED:
        scope_task = asyncio.create_task(JevRanker(client).scope(analysis.normalized_query))

    # The units (and every vector) are in Uzbek, so ru/en questions are also searched through an Uzbek translation.
    # The translation call runs while the original-language retrieval is in flight.
    translation = None
    if not use_llm:
        pass
    elif language in ("ru", "en"):
        translation = asyncio.create_task(QueryTranslator.to_uzbek(analysis.normalized_query, language, client))
    elif language == "uz" and settings.QUERY_NORMALIZE_UZ:
        # chat questions are often Cyrillic and misspelled; a standard-Latin rewrite is searched as well
        translation = asyncio.create_task(QueryTranslator.normalize_uzbek(analysis.raw_query, client))
    # A long story is also split into short legal sub-questions, each searched on its own (see fuse_aspect_candidates)
    subquestions_task: Optional[asyncio.Task] = None
    if use_llm and _wants_subquestions(analysis):
        subquestions_task = asyncio.create_task(QueryTranslator.legal_subquestions(
            analysis.raw_query, client, terms=LegalSynonymExpander.expand_terms(analysis.normalized_query, max_terms=8),
        ))
    tasks = [t for t in (scope_task, translation, subquestions_task) if t]
    try:
        candidates = await retriever.retrieve(
            analysis, top_k=top_k, precomputed_query_vector=query_vector, use_vector=use_vector,
        )
        translated = await translation if translation else None

        uz_analysis = None
        if translated and language == "uz" and not _use_uz_rewrite(translated, analysis):
            translated = None
        if translated:
            uz_analysis = QueryAnalyzer.analyze(translated, user_language="uz")
            uz_candidates = await retriever.retrieve(uz_analysis, top_k=top_k, use_vector=use_vector)
            candidates = merge_candidates([candidates, uz_candidates], limit=top_k + 10)

        subquestions = (await subquestions_task) if subquestions_task else None
        if subquestions:
            aspect_lists = await asyncio.gather(*(
                retriever.retrieve(QueryAnalyzer.analyze(q, user_language="uz"), top_k=top_k, use_vector=use_vector)
                for q in subquestions
            ))
            # every sub-question brings its own norms, so the pool (and Jev's share of it) grows with their number
            limit = top_k + 10 + settings.JEV_RERANK_UNITS_PER_SUBQUESTION * len(subquestions)
            candidates = fuse_aspect_candidates(candidates, list(aspect_lists), limit=limit)

        # A client-selected legal domain is a hint, not a filter: act/unit categories are heuristic labels and a
        # hard filter silently drops a correct article whenever the label is imperfect. Matching units get a boost.
        if category and category != "all":
            art_map = store.get_articles_batch([c.canonical_id for c in candidates])
            for c in candidates:
                art = art_map.get(c.canonical_id)
                if art is not None and art.metadata.category == category:
                    c.rrf_score += CATEGORY_BOOST
            candidates.sort(key=lambda c: c.rrf_score, reverse=True)

        expanded = expand_cross_references(candidates, store, max_extra=max_extra)
        valid, warnings = apply_status_and_amendment_filter(expanded, store)

        rerank_query = analysis.normalized_query if not uz_analysis else f"{analysis.normalized_query}\n{uz_analysis.normalized_query}"
        if subquestions:
            rerank_query += "\n" + "\n".join(subquestions)

        reranker = Reranker(client=client)
        contexts = await reranker.rerank(
            query=rerank_query,
            language=language,
            candidates=valid,
            store=store,
            top_n=rerank_top_n,
            use_model=use_reranker,
            subquestions=subquestions,
        )

        # Editorial curated answers that the reranker found relevant become the primary answer; their linked Lex.uz
        # norms are added even when retrieval missed them. Weak or unpublished curated hits are dropped.
        if any(c.article.canonical_id.startswith("qa_") or c.article.canonical_id.startswith("hp_") for c in contexts):
            try:
                from src.editorial.retrieval import (
                    add_linked_act_units,
                    curated_relevance_threshold,
                    ensure_curated_contexts,
                )
                from src.editorial.store import EditorialStore
                editorial = EditorialStore()
                contexts = ensure_curated_contexts(
                    contexts, store, editorial,
                    min_rerank_score=curated_relevance_threshold(reranker.last_provider),
                )
                contexts = add_linked_act_units(contexts, store, editorial, rerank_query)
            except Exception:
                logger.warning("Curated-context ordering failed; serving lex norms only.", exc_info=True)
                contexts = [c for c in contexts if not c.article.canonical_id.startswith("qa_") and not c.article.canonical_id.startswith("hp_")]

        decision: Optional[GateDecision] = None
        in_scope: Optional[float] = None
        if apply_gate:
            if reranker.last_provider == "jev":
                in_scope = await scope_task if scope_task else None
                top_prob = max((c.rerank_score for c in contexts if c.rerank_score is not None), default=None)
                decision = jev_gate_decision(in_scope, reranker.last_answerable, top_prob)
                if not decision.answerable:
                    logger.info(f"Relevance gate refused: {decision.reason} (conf={decision.confidence:.2f})")
                    contexts = []
            else:
                # the model ranker was off or failed; a scope judgement already asked for is still used (below)
                if scope_task:
                    try:
                        in_scope = await scope_task
                    except Exception:
                        in_scope = None
                decision = RelevanceGate().assess(
                    query=rerank_query,
                    scored=candidates,                 # scores of the original hybrid hits (expanded ones carry none)
                    context_texts=[c.article.get_text(language) for c in contexts],
                    rerank_scores=[c.rerank_score for c in contexts if c.rerank_score is not None],
                    is_mock=client.is_mock,
                )
                if in_scope is not None and settings.GATE_JEV_SCOPE_ENABLED:
                    if in_scope < settings.GATE_JEV_MIN_IN_SCOPE:
                        decision = GateDecision(False, "jev_out_of_scope", in_scope)
                    elif (not decision.answerable and decision.reason == "low_relevance"
                          and in_scope >= settings.GATE_SCOPE_RESCUE and contexts):
                        # only the lexical gate is overridden: a cross-encoder that found the evidence irrelevant
                        # (low_reranker_score) is a judgement about the units, which the scope judge does not make
                        logger.info(f"Lexical gate refused ({decision.reason}) but the scope judge says {in_scope:.2f}: answering")
                        decision = GateDecision(True, "scope_rescue", in_scope)
                if not decision.answerable:
                    logger.info(f"Relevance gate refused: {decision.reason} (conf={decision.confidence:.2f})")
                    contexts = []
        else:
            if scope_task:
                scope_task.cancel()

        # An act the question names (number and year) that a unit of the corpus repealed: that unit goes first, so the
        # answer says the act lost force instead of describing it as current law (see repeal_notices).
        notice_ids: List[str] = []
        if contexts:
            notices = await asyncio.to_thread(repeal_notices, analysis.raw_query, store)
            if notices:
                notice_ids = [a.canonical_id for a in notices]
                present = {c.article.canonical_id: c for c in contexts}
                front = [present.get(a.canonical_id) or RetrievedArticleContext(
                    article=a, final_score=0.0, source_tag="repeal_notice") for a in notices]
                contexts = front + [c for c in contexts if c.article.canonical_id not in notice_ids]

        signals = {
            "rerank_provider": reranker.last_provider,
            "repeal_notices": notice_ids,
            "jev_in_scope": in_scope,
            "jev_answerable": reranker.last_answerable,
            "subquestions": subquestions or [],
        }

        return RetrievalResult(
            contexts=contexts,
            candidates=candidates,
            status_warnings=warnings,
            decision=decision,
            signals=signals,
        )
    finally:
        _discard_tasks(tasks)


async def retrieve_within(deadline_s: float, **kwargs) -> RetrievalResult:
    """
    retrieve_contexts with a deadline. A provider that hangs (no error, no answer) would hold the request for minutes in
    the embedding, translation, scope and ranking calls, each with its own long HTTP timeout and retries. Past the deadline
    the question is searched again by full-text search with no model call, so the visitor still gets the matching norms.
    """
    try:
        return await asyncio.wait_for(retrieve_contexts(**kwargs), timeout=deadline_s)
    except asyncio.TimeoutError:
        logger.error(f"Retrieval exceeded {deadline_s:.0f}s (provider not answering): full-text search only")
        kwargs.update(query_vector=None, use_vector=False, use_reranker=False, use_llm=False)
        result = await retrieve_contexts(**kwargs)
        result.signals["retrieval_timeout"] = True
        return result
