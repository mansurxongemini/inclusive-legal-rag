"""Kuzatuvchi: legal_links snapshot'larini store'dagi joriy holat bilan solishtiradi."""

import logging
from typing import Optional, Tuple

from src.config import settings
from src.editorial import service as svc
from src.editorial.doc_watch import (
    archive_law_texts,
    doc_changes,
    doc_change_summary,
    doc_snapshot,
    is_doc_link,
    law_id_of,
    refresh_doc_link,
)
from src.editorial.store import EditorialStore

logger = logging.getLogger(__name__)


def change_marker(article) -> Tuple[str, str]:
    """(kind, marker) of the live norm; marker identifies the state an editor decides on."""
    if article is None:
        return "norm_removed", "removed:missing"
    if article.metadata.status.value == "repealed":
        return "norm_repealed", f"repealed:{article.metadata.source_hash or ''}"
    return "norm_amended", article.metadata.source_hash or "amended"


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

    # 1. Boshida: ochiq document_amended bildirishnomalarini qayta tekshir —
    # endi real o'zgarish bo'lmasa: snapshot'ni yangila va resolution="auto:no_real_change",
    # resolved_by="system" bilan yop (hisob: auto_resolved).
    auto_resolved = 0
    open_notifs, _ = editorial.list_notifications(status="open", limit=10000)
    for notif in open_notifs:
        if notif["kind"] != "document_amended" or not is_doc_link(notif["canonical_id"]):
            continue
        cid = notif["canonical_id"]
        law_id = law_id_of(cid)
        links_for_owner = editorial.list_links(owner_type=notif["owner_type"], owner_id=notif["owner_id"])
        link = next((l for l in links_for_owner if l["canonical_id"] == cid), None)
        old_state_json = link.get("snapshot_text") if link else notif.get("old_text")
        changes = doc_changes(store, editorial, law_id, old_state_json or "")
        if not changes["real"]:
            if link:
                refresh_doc_link(store, editorial, link)
            editorial.resolve_notification(
                notif["id"],
                resolution="auto:no_real_change",
                resolved_by="system",
            )
            auto_resolved += 1

    # 2. Har tekshiruvda butun-hujjat havolalari aktlarining matnlari arxivlansin (har akt bir marta)
    links = editorial.list_all_links()
    archived_law_ids = set()
    for link in links:
        cid = link["canonical_id"]
        if is_doc_link(cid):
            lid = law_id_of(cid)
            if lid not in archived_law_ids:
                archive_law_texts(store, editorial, lid)
                archived_law_ids.add(lid)

    created, suspended, rebased = 0, 0, 0
    for link in links:
        owner_type, owner_id = link["owner_type"], link["owner_id"]
        canonical_id = link["canonical_id"]

        if is_doc_link(canonical_id):
            law_id = law_id_of(canonical_id)
            snap = doc_snapshot(store, law_id)
            if snap is None:
                kind, marker = "norm_removed", "removed:missing"
                old_text, new_text = "", f"Hujjat bazadan olib tashlangan: {law_id}"
            elif snap[2] == "repealed":
                kind, marker = "norm_repealed", f"repealed:{snap[1]}"
                old_text = ""
                new_text = doc_change_summary(store, law_id, link.get("snapshot_text") or "", editorial=editorial)
            else:
                changes = doc_changes(store, editorial, law_id, link.get("snapshot_text") or "")
                if not changes["real"]:
                    if snap[1] != (link.get("snapshot_hash") or ""):
                        refresh_doc_link(store, editorial, link)
                        rebased += 1
                    continue
                kind = "document_amended"
                marker = snap[1]
                old_text = ""
                new_text = doc_change_summary(store, law_id, link.get("snapshot_text") or "", editorial=editorial)
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
            continue
        created += 1
        if owner_type == "curated" and settings.EDITORIAL_SUSPEND_ON_CHANGE:
            try:
                answer = editorial.get_answer(int(owner_id))
            except ValueError:
                answer = None
            if answer and answer["status"] == "published":
                svc.suspend_answer(store, editorial, int(owner_id), action="auto_needs_review")
                suspended += 1

    return {
        "checked_links": len(links),
        "new_notifications": created,
        "suspended_answers": suspended,
        "rebased": rebased,
        "auto_resolved": auto_resolved,
    }
