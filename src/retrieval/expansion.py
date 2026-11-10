import logging
from typing import List, Set
from src.schema.canonical import CanonicalArticle
from src.storage.hybrid_store import HybridStore
from src.retrieval.hybrid_retriever import ScoredArticle

logger = logging.getLogger(__name__)


def expand_cross_references(
    candidates: List[ScoredArticle],
    store: HybridStore,
    max_extra: int = 6,
) -> List[ScoredArticle]:
    """
    Expands candidate set by 1-hop following cross-references (implements, refers_to).
    Capped at max_extra articles.
    """
    existing_ids: Set[str] = {c.canonical_id for c in candidates}
    expanded_results: List[ScoredArticle] = list(candidates)
    added_count = 0

    # Batch load candidates
    candidates_map = store.get_articles_batch([c.canonical_id for c in candidates])

    # 1. 1-hop explicit statutory cross-references
    for candidate in candidates:
        if added_count >= max_extra:
            break

        article: CanonicalArticle = candidates_map.get(candidate.canonical_id)
        if not article or not article.metadata.cross_references:
            continue


        for ref in article.metadata.cross_references:
            target_id = ref.target_canonical_id
            if target_id not in existing_ids:
                target_art = store.get_article(target_id)
                if target_art:
                    existing_ids.add(target_id)
                    inherited_score = candidate.rrf_score * 0.8
                    expanded_results.append(ScoredArticle(
                        canonical_id=target_id,
                        rrf_score=inherited_score,
                        source_tag=f"expanded_from:{candidate.canonical_id}:{ref.ref_type.value}",
                    ))
                    added_count += 1
                    if added_count >= max_extra:
                        break

    # Cross-references are the only expansion source: hand-written article chains from other legal domains
    # (mortgage, LLC governance, MJtK) used ids that are not part of this corpus.
    return expanded_results
