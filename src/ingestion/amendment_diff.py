import difflib
import logging
from typing import Optional, Tuple
from src.schema.canonical import CanonicalArticle, ArticleStatus, AmendmentRecord
from src.storage.hybrid_store import HybridStore
from src.ingestion.review_queue import ReviewQueue, ReviewQueueItem

logger = logging.getLogger(__name__)


def check_and_apply_amendment(
    new_article: CanonicalArticle,
    store: HybridStore,
    review_queue: ReviewQueue,
    amending_law_number: str = "O'RQ-AMENDMENT",
) -> Tuple[bool, Optional[str]]:
    """
    Checks if an article with canonical_id already exists:
    - If hash changed, creates a diff summary and enqueues into review_queue.
    - Does NOT automatically overwrite live data until approved, fulfilling Section 2 item 6.
    Returns (has_changed: bool, diff_summary: str).
    """
    existing: Optional[CanonicalArticle] = store.get_article(new_article.canonical_id)
    if not existing:
        return False, None

    old_text = existing.get_text("uz")
    new_text = new_article.get_text("uz")

    if existing.metadata.source_hash == new_article.metadata.source_hash:
        return False, "Matnda o'zgarish yo'q (No content change)."

    # Generate unified diff
    diff_lines = list(difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile="Eski tahrir (Active)",
        tofile="Yangi tahrir (Proposed)",
        lineterm=""
    ))
    diff_summary = "\n".join(diff_lines)

    # Enqueue change for legal human review
    item = ReviewQueueItem(
        canonical_id=new_article.canonical_id,
        change_type="amended_article",
        diff_summary=diff_summary,
        proposed_json=new_article.model_dump_json(),
        status="pending"
    )
    item_id = review_queue.enqueue(item)
    logger.info(f"Article {new_article.canonical_id} modification enqueued for review (Queue ID: {item_id})")

    return True, diff_summary
