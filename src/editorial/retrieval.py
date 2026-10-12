"""Retrieval helper: published curated answers and Huquq+ articles become the primary answer source."""

import logging
from typing import List, Optional, Tuple

from src.config import settings
from src.editorial.store import EditorialStore
from src.retrieval.reranker import RetrievedArticleContext
from src.schema.canonical import ArticleStatus
from src.storage.hybrid_store import HybridStore

logger = logging.getLogger(__name__)

# without a cross-encoder score (mock / fallback ranking) a curated answer must be among the top hits
_UNSCORED_MAX_POSITION = 3


def _answer_id(canonical_id: str) -> Optional[int]:
    try:
        return int(canonical_id.split("_", 1)[1])
    except (ValueError, IndexError):
        return None


def _parse_hp_canonical_id(canonical_id: str) -> Optional[Tuple[str, int]]:
    """hp_{lang}_{wp_id}_{n} -> (lang, wp_id)"""
    parts = canonical_id.split("_")
    if len(parts) >= 4 and parts[0] == "hp":
        try:
            return parts[1], int(parts[2])
        except (ValueError, IndexError):
            return None
    return None


def _get_hp_post_status(lang: str, wp_id: int) -> Optional[str]:
    from src.integrations.huquqplus_sync import get_huquqplus_db_path
    from src.storage.sqlite_utils import connect as _sqlite_conn
    try:
        with _sqlite_conn(get_huquqplus_db_path(), timeout=10.0) as conn:
            row = conn.execute(
                "SELECT status FROM hp_posts WHERE wp_id = ? AND lang = ?", (wp_id, lang)
            ).fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.warning(f"Could not read hp_posts status for {lang}:{wp_id}: {e}")
        return None


def linked_lex_canonical_ids(editorial: EditorialStore, answer_id: int) -> List[str]:
    links = editorial.list_links(owner_type="curated", owner_id=str(answer_id))
    return [l["canonical_id"] for l in links if l.get("canonical_id")]


def ensure_curated_contexts(
    contexts: List[RetrievedArticleContext],
    store: HybridStore,
    editorial: EditorialStore,
    min_rerank_score: Optional[float] = None,
) -> List[RetrievedArticleContext]:
    """
    Curated answers and Huquq+ portal articles are indexed like any other unit, so they reach `contexts`
    only through normal hybrid retrieval + reranking. Here they are filtered and re-ordered:

    * Curated answers (qa_):
      - Must be published;
      - Must be relevant (rerank_score >= threshold or position < 3);
      - Relevant moves to the front, linked Lex.uz norms added as legal_basis.
    * Huquq+ articles (hp_):
      - Must be active in hp_posts (not suspended or deleted);
      - If EDITORIAL_SUSPEND_ON_CHANGE is True, must have no open notifications in editorial;
      - Must be relevant (rerank_score >= threshold or position < 3);
      - Stand after curated, before raw lex norms; their resolved lex cross_references added (rerank_score=None).
    """
    threshold = settings.GATE_MIN_RERANK_SCORE if min_rerank_score is None else min_rerank_score

    primary: List[RetrievedArticleContext] = []
    hp_primary: List[RetrievedArticleContext] = []
    rest: List[RetrievedArticleContext] = []

    for position, ctx in enumerate(contexts):
        cid = ctx.article.canonical_id
        if cid.startswith("qa_"):
            aid = _answer_id(cid)
            answer = editorial.get_answer(aid) if aid is not None else None
            if not answer or answer.get("status") != "published":
                logger.warning(f"Dropping stale curated projection {cid} (answer not published)")
                continue
            relevant = (ctx.rerank_score >= threshold) if ctx.rerank_score is not None \
                else position < _UNSCORED_MAX_POSITION
            if relevant:
                primary.append(ctx)
        elif cid.startswith("hp_"):
            parsed = _parse_hp_canonical_id(cid)
            if not parsed:
                continue
            lang, wp_id = parsed
            post_status = _get_hp_post_status(lang, wp_id)
            if post_status != "active":
                logger.warning(f"Dropping hp context {cid} (post status: {post_status})")
                continue

            if settings.EDITORIAL_SUSPEND_ON_CHANGE:
                open_notifs = editorial.open_notifications_for_owner(
                    owner_type="huquqplus", owner_id=f"{lang}:{wp_id}"
                )
                if open_notifs:
                    logger.warning(f"Dropping hp context {cid} (open notifications exist)")
                    continue

            relevant = (ctx.rerank_score >= threshold) if ctx.rerank_score is not None \
                else position < _UNSCORED_MAX_POSITION
            if relevant:
                hp_primary.append(ctx)
        else:
            rest.append(ctx)

    if not primary and not hp_primary:
        return rest

    have = {c.article.canonical_id for c in primary} | {c.article.canonical_id for c in hp_primary} | {c.article.canonical_id for c in rest}

    basis: List[RetrievedArticleContext] = []
    for ctx in primary:
        for cid in linked_lex_canonical_ids(editorial, _answer_id(ctx.article.canonical_id)):
            if cid in have:
                continue
            linked = store.get_article(cid)
            if linked is None or linked.metadata.status != ArticleStatus.ACTIVE:
                continue
            basis.append(RetrievedArticleContext(article=linked, final_score=ctx.final_score, source_tag="legal_basis"))
            have.add(cid)

    hp_basis: List[RetrievedArticleContext] = []
    for ctx in hp_primary:
        for ref in ctx.article.metadata.cross_references:
            target_cid = ref.target_canonical_id
            if target_cid in have:
                continue
            linked = store.get_article(target_cid)
            if linked is None or linked.metadata.status != ArticleStatus.ACTIVE:
                continue
            hp_basis.append(RetrievedArticleContext(
                article=linked,
                final_score=ctx.final_score,
                source_tag="legal_basis",
                rerank_score=None,
            ))
            have.add(target_cid)

    # curated answers first, then their bases, then huquqplus articles, then their bases, then rest
    return primary + basis + hp_primary + hp_basis + rest
