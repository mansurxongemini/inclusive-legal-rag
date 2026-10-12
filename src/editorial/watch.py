"""Kuzatuvchi: legal_links snapshot'larini store'dagi joriy holat bilan solishtiradi."""

import logging
from typing import Optional, Tuple

from src.config import settings
from src.editorial import service as svc
from src.editorial.doc_watch import doc_change_summary, doc_snapshot, is_doc_link, law_id_of
from src.editorial.store import EditorialStore

logger = logging.getLogger(__name__)


def change_marker(article) -> Tuple[str, str]:
    """(kind, marker) of the live norm; marker identifies the state an editor decides on."""
    if article is None:
        return "norm_removed", "removed:missing"
    if article.metadata.status.value == "repealed":
        return "norm_repealed", f"repealed:{article.metadata.source_hash or ''}"
    return "norm_amended", article.metadata.source_hash or "amended"


def _document_state(store, link: dict) -> Tuple[str, str, str, str]:
    """(kind, marker, old_text, new_text) of a whole-act link; the card lists the changed units."""
    law_id = law_id_of(link["canonical_id"])
    snap = doc_snapshot(store, law_id)
    if snap is None:
        return "norm_removed", "removed:missing", "", f"Hujjat bazadan olib tashlangan: {law_id}"
    _, aggregate, status = snap
    summary = doc_change_summary(store, law_id, link.get("snapshot_text") or "")
    if status == "repealed":
        return "norm_repealed", f"repealed:{aggregate}", "", summary
    return "document_amended", aggregate, "", summary


def check_legal_links(store, editorial: Optional[EditorialStore] = None) -> dict:
    """Compares every legal link snapshot with the live store article.

    - hash farqi -> norm_amended
    - status REPEALED -> norm_repealed
    - topilmadi -> norm_removed
    At most one open notification per (owner, norm); a change the editor already decided on
    (link.acknowledged_marker) is not reported again. Freshly flagged published answers are suspended to
    needs_review and removed from search.
    """
    editorial = editorial or EditorialStore()
    links = editorial.list_all_links()
    created, suspended = 0, 0
    for link in links:
        owner_type, owner_id = link["owner_type"], link["owner_id"]
        canonical_id = link["canonical_id"]
        if is_doc_link(canonical_id):
            kind, marker, old_text, new_text = _document_state(store, link)
        else:
            article = store.get_article(canonical_id) if store else None
            kind, marker = change_marker(article)
            old_text = link.get("snapshot_text") or ""
            new_text = (article.get_text("uz") or "") if article is not None else ""
        if kind in ("norm_amended", "document_amended") and marker == (link.get("snapshot_hash") or ""):
            continue                                        # unchanged since it was linked / last confirmed
        if marker == (link.get("acknowledged_marker") or ""):
            continue                                        # editor already decided on exactly this state
        notif = editorial.create_notification(
            kind=kind, owner_type=owner_type, owner_id=owner_id, canonical_id=canonical_id,
            old_hash=link.get("snapshot_hash") or "", new_hash=marker,
            old_text=old_text, new_text=new_text,
        )
        if notif is None:
            continue  # an open notification for this norm is already waiting for the editor
        created += 1
        if owner_type == "curated" and settings.EDITORIAL_SUSPEND_ON_CHANGE:
            try:
                answer = editorial.get_answer(int(owner_id))
            except ValueError:
                answer = None
            if answer and answer["status"] == "published":
                svc.suspend_answer(store, editorial, int(owner_id), action="auto_needs_review")
                suspended += 1
    return {"checked_links": len(links), "new_notifications": created, "suspended_answers": suspended}
