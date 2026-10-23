"""Retrieval helper: published curated answers lead the context; Huquq+ articles follow the statutory norms."""

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


def curated_relevance_threshold(rerank_provider: str) -> float:
    """
    Minimum rerank score for a curated answer / Huquq+ article to count as relevant.

    The two rerankers score on different scales. A cross-encoder (Cohere) rates every passage on its own, so
    GATE_MIN_RERANK_SCORE (0.70) is meaningful. Jev picks the best passage out of a list: its scores sum to 1, so
    any passage that is not the single top pick sits far below 0.70 (on the stress set no top pick scored under
    0.30, hence a runner-up can never reach 0.70). For Jev "scored at least RERANK_PICK_MIN" is the existing
    definition of a pick.
    """
    if rerank_provider == "jev":
        return settings.CURATED_MIN_JEV_SCORE
    return settings.GATE_MIN_RERANK_SCORE


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
      - Must be relevant (rerank_score >= threshold; position < 3 only when it has no rerank score);
      - Relevant moves to the front, linked Lex.uz norms added as legal_basis.
    * Huquq+ articles (hp_):
      - Must be active in hp_posts (not suspended or deleted);
      - If EDITORIAL_SUSPEND_ON_CHANGE is True, must have no open notifications in editorial;
      - Must be relevant (rerank_score >= threshold; position < 3 only when it has no rerank score);
      - Their resolved lex cross_references are added (rerank_score=None);
      - Never stand before a Lex.uz norm: a portal article is a practical explanation that may be older than the
        law it describes (sums, repealed acts), so it follows every statutory unit of the context.
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

    # curated answers first, then their bases, then high-scoring rerank picks, then huquqplus bases, then other
    # rest contexts; huquqplus articles come last, after all statutory text
    picks: List[RetrievedArticleContext] = []
    others: List[RetrievedArticleContext] = []
    for c in rest:
        if c.rerank_score is not None and c.rerank_score >= settings.RERANK_PICK_MIN:
            picks.append(c)
        else:
            others.append(c)

    return primary + basis + picks + hp_basis + others + hp_primary


_STOP_STEMS = {"bo'la", "bo'ld", "qanda", "qanday", "nechi", "necha", "uchun", "yoki", "bilan", "mumki", "kerak",
               "olsam", "olish", "bormi", "qilib", "hamda", "shaxs", "tarti"}


def _stems(text: str) -> set:
    """5-letter prefixes of the words: crude Uzbek stemming ("kartamga" ~ "kartasi", "vaucherga" ~ "vaucher")."""
    import re
    norm = (text or "").lower()
    for ch in "ʻʼ‘’`´":
        norm = norm.replace(ch, "'")
    return {w[:5] for w in re.findall(r"[a-z'][a-z'-]{3,}", norm)} - _STOP_STEMS


def add_linked_act_units(contexts: List[RetrievedArticleContext], store: HybridStore, editorial: EditorialStore,
                         query: str, per_act: int = 2, max_acts: int = 3, min_overlap: int = 2
                         ) -> List[RetrievedArticleContext]:
    """
    A Huquq+ article usually cites a whole act (a Lex.uz link without an article anchor), so it has no
    cross_references and the answer would rest on the article alone. For each such whole-act link of a Huquq+
    context, the act's units sharing the most query words are added after the leading block
    (curated, legal bases, and high-scoring rerank picks), before the first unscored or low-scoring non-basis
    context or the first Huquq+ article (statutory text never follows a Huquq+ article), or at the end.
    """
    from src.editorial.doc_watch import is_doc_link, law_id_of, law_units

    q = _stems(query)
    if not q:
        return contexts
    have = {c.article.canonical_id for c in contexts}
    linked_units: List[RetrievedArticleContext] = []
    acts_done: set = set()
    for ctx in contexts:
        parsed = _parse_hp_canonical_id(ctx.article.canonical_id)
        if not parsed:
            continue
        lang, wp_id = parsed
        for link in editorial.list_links(owner_type="huquqplus", owner_id=f"{lang}:{wp_id}"):
            if len(acts_done) >= max_acts or not is_doc_link(link["canonical_id"]):
                continue
            law_id = law_id_of(link["canonical_id"])
            if law_id in acts_done:
                continue
            acts_done.add(law_id)
            ids = [cid for cid in law_units(store, law_id) if cid not in have]
            scored = []
            for cid, art in store.get_articles_batch(ids).items():
                if art.metadata.status != ArticleStatus.ACTIVE:
                    continue
                overlap = len(q & _stems(art.get_text("uz")))
                if overlap >= min_overlap:
                    scored.append((overlap, cid, art))
            for overlap, cid, art in sorted(scored, key=lambda x: (-x[0], x[1]))[:per_act]:
                linked_units.append(RetrievedArticleContext(article=art, final_score=ctx.final_score,
                                                           source_tag="legal_basis", rerank_score=None))
                have.add(cid)

    if not linked_units:
        return contexts

    insert_idx: Optional[int] = None
    for idx, ctx in enumerate(contexts):
        cid = ctx.article.canonical_id
        if cid.startswith("qa_") or ctx.source_tag == "legal_basis":
            continue
        if cid.startswith("hp_") or ctx.rerank_score is None or ctx.rerank_score < settings.RERANK_PICK_MIN:
            insert_idx = idx
            break

    if insert_idx is not None:
        return contexts[:insert_idx] + linked_units + contexts[insert_idx:]
    return contexts + linked_units
