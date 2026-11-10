import logging
from typing import List, Set, Tuple
from src.schema.canonical import ArticleStatus
from src.storage.hybrid_store import HybridStore
from src.retrieval.hybrid_retriever import ScoredArticle

logger = logging.getLogger(__name__)


def apply_status_and_amendment_filter(
    candidates: List[ScoredArticle],
    store: HybridStore,
) -> Tuple[List[ScoredArticle], List[dict]]:
    """
    Inspects candidate articles for amended or repealed status.
    If an article is repealed or amended and has `superseded_by`,
    pulls in the active replacement article and flags the status.
    Returns (updated_candidates, list_of_status_warnings).
    """
    updated: List[ScoredArticle] = []
    status_warnings: List[dict] = []
    existing_ids: Set[str] = {c.canonical_id for c in candidates}

    # Batch load candidate articles
    articles_map = store.get_articles_batch(list(existing_ids))

    for candidate in candidates:
        article = articles_map.get(candidate.canonical_id)
        if not article:
            continue


        status = article.metadata.status
        if status in (ArticleStatus.REPEALED, ArticleStatus.AMENDED):
            superseded_id = article.metadata.superseded_by
            warning = {
                "canonical_id": article.canonical_id,
                "article_number": article.metadata.article_number,
                "status": status.value,
                "superseded_by": superseded_id,
                "message": f"{article.metadata.article_number} {status.value} qilingan." + (
                    f" Amaldagi yangi tahrir: {superseded_id}." if superseded_id else ""
                ),
            }
            status_warnings.append(warning)

            # If superseded_by exists and is not in list, add it as replacement
            if superseded_id and superseded_id not in existing_ids:
                replacement_art = store.get_article(superseded_id)
                if replacement_art:
                    existing_ids.add(superseded_id)
                    updated.append(ScoredArticle(
                        canonical_id=superseded_id,
                        rrf_score=candidate.rrf_score + 0.01,  # Prioritize active replacement
                        source_tag=f"superseded_replacement_for:{candidate.canonical_id}",
                    ))

        updated.append(candidate)

    # Sort again
    updated.sort(key=lambda x: x.rrf_score, reverse=True)
    return updated, status_warnings
