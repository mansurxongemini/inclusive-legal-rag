import logging
from typing import List, Set
from src.schema.canonical import CanonicalArticle, RefType
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

    # 2. Blanket Disposition Synergy (Connecting Blanket Norms to Regulations)
    BLANKET_COMPANIONS = {
        "mjtk_code_art_128": ["vmq_172_yhq_art_65", "vmq_172_yhq_art_16"],
        "mjtk_code_art_128_3": ["vmq_172_yhq_art_76", "vmq_172_yhq_art_77"],
        "mjtk_code_art_128_4": ["vmq_172_yhq_art_28", "vmq_172_yhq_art_31"],
        "mjtk_code_art_128_5": ["vmq_172_yhq_art_84"],
        "mjtk_code_art_128_6": ["vmq_172_yhq_art_89", "vmq_172_yhq_art_90"],
    }

    for c in candidates:
        if added_count >= max_extra:
            break
        if c.canonical_id in BLANKET_COMPANIONS:
            for b_cid in BLANKET_COMPANIONS[c.canonical_id]:
                if added_count >= max_extra:
                    break
                if b_cid not in existing_ids:
                    b_art = store.get_article(b_cid)
                    if b_art:
                        existing_ids.add(b_cid)
                        expanded_results.append(ScoredArticle(
                            canonical_id=b_cid,
                            rrf_score=c.rrf_score * 0.85,
                            source_tag=f"blanket_companion:{c.canonical_id}",
                        ))
                        added_count += 1

    # 3. German Dogmatics-Inspired Procedural & Jurisdictional Synergy
    # Automatically provide procedural deadlines and remedies (Fristen & Rechtsbehelfe)
    PROCEDURAL_COMPANIONS = {
        "mjtk_code": ["mjtk_code_art_332_1", "mjtk_code_art_315", "mjtk_code_art_316", "mjtk_code_art_318"],
        "mehnat_code": ["mehnat_code_art_560", "mehnat_code_art_543"],
        "jinoyat_code": ["jinoyat_code_art_66_1", "jinoyat_code_art_64"],
        "fuqarolik_code": ["fuqarolik_code_1_art_150"],
        "soliq_code": ["soliq_code_art_231"],
    }

    if added_count < max_extra:
        matched_codes = {}
        for c in candidates:
            for code_key in PROCEDURAL_COMPANIONS:
                if code_key in c.canonical_id:
                    matched_codes[code_key] = max(matched_codes.get(code_key, 0.0), c.rrf_score)

        for code_key, max_parent_score in matched_codes.items():
            for companion_cid in PROCEDURAL_COMPANIONS[code_key]:
                if added_count >= max_extra:
                    break
                if companion_cid not in existing_ids:
                    comp_art = store.get_article(companion_cid)
                    if comp_art:
                        existing_ids.add(companion_cid)
                        expanded_results.append(ScoredArticle(
                            canonical_id=companion_cid,
                            rrf_score=max_parent_score * 0.70,
                            source_tag=f"procedural_companion:{code_key}",
                        ))
                        added_count += 1

    return expanded_results
