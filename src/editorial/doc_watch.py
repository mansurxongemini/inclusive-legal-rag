"""
Document-level legal links.

Most Lex.uz references in Huquq+ articles point at a whole act (no article anchor). Such a reference is watched as
a link to `law:<law_id>`: its snapshot is the state (hash + status) of every unit of the act that is in the corpus,
so any amendment of those units raises one "document_amended" notification listing what changed.
"""
import hashlib
import json
from typing import Dict, List, Optional, Tuple

DOC_PREFIX = "law:"


def doc_link_id(law_id: str) -> str:
    return f"{DOC_PREFIX}{law_id}"


def is_doc_link(canonical_id: str) -> bool:
    return (canonical_id or "").startswith(DOC_PREFIX)


def law_id_of(canonical_id: str) -> str:
    return canonical_id[len(DOC_PREFIX):]


def law_units(store, law_id: str) -> Dict[str, Tuple[str, str, str]]:
    """canonical_id -> (source_hash, status, article label) of the act's statutory units."""
    with store.fts_store._get_connection() as conn:
        rows = conn.execute("""
            SELECT canonical_id, source_hash, status, json_extract(json_data, '$.metadata.article_number')
            FROM articles_metadata
            WHERE json_extract(json_data, '$.metadata.law_id') = ?
              AND coalesce(json_extract(json_data, '$.metadata.source_type'), 'lex') = 'lex'
        """, (law_id,)).fetchall()
    return {r[0]: (r[1] or "", r[2] or "active", r[3] or r[0]) for r in rows}


def law_units_full(store, law_id: str) -> List[dict]:
    """Fetch full details of an act's statutory units: canonical_id, hash, status, label, text (uz), url."""
    if store is None or not hasattr(store, "fts_store") or store.fts_store is None:
        return []
    with store.fts_store._get_connection() as conn:
        rows = conn.execute("""
            SELECT
                canonical_id,
                source_hash,
                status,
                coalesce(json_extract(json_data, '$.metadata.article_number'), canonical_id),
                coalesce(json_extract(json_data, '$.translations.uz'), ''),
                coalesce(json_extract(json_data, '$.metadata.source_url'), '')
            FROM articles_metadata
            WHERE json_extract(json_data, '$.metadata.law_id') = ?
              AND coalesce(json_extract(json_data, '$.metadata.source_type'), 'lex') = 'lex'
        """, (law_id,)).fetchall()
    return [
        {
            "canonical_id": r[0],
            "hash": r[1] or "",
            "status": r[2] or "active",
            "label": r[3] or r[0],
            "text": r[4] or "",
            "url": r[5] or "",
        }
        for r in rows
    ]


def archive_law_texts(store, editorial, law_id: str) -> int:
    """Archive texts of all units in this act into unit_text_archive."""
    if store is None or editorial is None or not hasattr(editorial, "archive_unit_texts"):
        return 0
    units = law_units_full(store, law_id)
    rows = [(u["hash"], u["label"], u["text"]) for u in units if u["hash"]]
    return editorial.archive_unit_texts(rows)


def law_label(store, law_id: str) -> str:
    if store is None or not hasattr(store, "fts_store") or store.fts_store is None:
        return law_id
    with store.fts_store._get_connection() as conn:
        row = conn.execute("""
            SELECT json_extract(json_data, '$.metadata.law_number'), json_extract(json_data, '$.metadata.law_title.uz')
            FROM articles_metadata WHERE json_extract(json_data, '$.metadata.law_id') = ? LIMIT 1
        """, (law_id,)).fetchone()
    if not row:
        return law_id
    number, title = row[0] or "", row[1] or ""
    return f"{number} {title}".strip()[:200] or law_id


def doc_snapshot(store, law_id: str) -> Optional[Tuple[str, str, str]]:
    """(state JSON, aggregate hash, status) of the act; None when no unit of it is in the corpus any more."""
    units = law_units(store, law_id)
    if not units:
        return None
    state = {cid: f"{h}|{st}" for cid, (h, st, _) in units.items()}
    state_json = json.dumps(state, sort_keys=True, ensure_ascii=False)
    aggregate = "sha256:" + hashlib.sha256(state_json.encode("utf-8")).hexdigest()
    status = "repealed" if all(st == "repealed" for _, st, _ in units.values()) else "active"
    return state_json, aggregate, status


def doc_changes(store, editorial, law_id: str, old_state_json: str) -> dict:
    """
    Compare current units of an act against the snapshotted state by TEXT HASH rather than ID.

    Rules:
    - If an old hash still exists in the live act -> unchanged, even if its canonical_id moved.
      If it was 'active' in snapshot but the live unit is now 'repealed' -> repealed.
    - If an old hash vanished and that canonical_id is still in the live act (with a new hash not in snapshot)
      -> changed {canonical_id, label, url, old_text, new_text}.
    - If an old hash vanished and its canonical_id is also not in live act (or not part of changed)
      -> removed {canonical_id, label, old_text}.
    - If a live unit's hash was not in snapshot and wasn't consumed by changed -> added {canonical_id, label, url, new_text}.

    Why real = bool(changed or removed or repealed):
    Adding new units to the corpus or re-ingesting with different filters does not invalidate
    existing articles. What invalidates an article or answer is when a statutory norm it relied on
    changes, is repealed, or is removed. Therefore, newly added units alone are never a reason to
    notify the editor.
    """
    try:
        old_state = json.loads(old_state_json or "{}")
    except (ValueError, TypeError):
        old_state = {}

    live_units = law_units_full(store, law_id)
    live_by_cid: Dict[str, dict] = {u["canonical_id"]: u for u in live_units}
    live_by_hash: Dict[str, dict] = {u["hash"]: u for u in live_units if u["hash"]}
    live_hashes = set(live_by_hash.keys())

    old_hashes = set()
    old_entries: Dict[str, dict] = {}
    for ocid, val in old_state.items():
        parts = val.split("|", 1) if isinstance(val, str) else []
        ohash = parts[0] if parts else ""
        ostatus = parts[1] if len(parts) > 1 else "active"
        old_entries[ocid] = {"hash": ohash, "status": ostatus}
        if ohash:
            old_hashes.add(ohash)

    archived = editorial.get_archived_texts(list(old_hashes)) if editorial else {}

    changed = []
    removed = []
    repealed = []
    used_in_changed_cids = set()

    for ocid, entry in old_entries.items():
        ohash = entry["hash"]
        ostatus = entry["status"]
        arch_lbl, arch_txt = archived.get(ohash, ("", ""))

        if ohash in live_hashes:
            live_u = live_by_hash[ohash]
            if ostatus == "active" and live_u["status"] == "repealed":
                repealed.append({
                    "canonical_id": live_u["canonical_id"],
                    "label": live_u["label"] or arch_lbl or ocid,
                    "url": live_u["url"],
                    "old_text": arch_txt,
                    "new_text": live_u["text"],
                })
        else:
            if ocid in live_by_cid and live_by_cid[ocid]["hash"] not in old_hashes:
                live_u = live_by_cid[ocid]
                changed.append({
                    "canonical_id": ocid,
                    "label": live_u["label"] or arch_lbl or ocid,
                    "url": live_u["url"],
                    "old_text": arch_txt,
                    "new_text": live_u["text"],
                })
                used_in_changed_cids.add(ocid)
            else:
                removed.append({
                    "canonical_id": ocid,
                    "label": arch_lbl or ocid,
                    "url": "",
                    "old_text": arch_txt,
                    "new_text": "",
                })

    added = []
    for u in live_units:
        if u["hash"] not in old_hashes and u["canonical_id"] not in used_in_changed_cids:
            added.append({
                "canonical_id": u["canonical_id"],
                "label": u["label"],
                "url": u["url"],
                "new_text": u["text"],
            })

    real = bool(changed or removed or repealed)
    return {
        "changed": changed,
        "removed": removed,
        "repealed": repealed,
        "added": added,
        "real": real,
    }


def doc_change_summary(store, law_id: str, old_state_json: str, editorial=None) -> str:
    """Human-readable list of the units that changed since the snapshot (shown in the notification card)."""
    if editorial is None:
        from src.editorial.store import get_editorial_store
        editorial = get_editorial_store()
    changes = doc_changes(store, editorial, law_id, old_state_json)
    lines = [f"Hujjat: {law_label(store, law_id)}"]
    for c in changes.get("changed", []):
        lines.append(f"• {c['label']} — o'zgartirildi")
    for r in changes.get("repealed", []):
        lines.append(f"• {r['label']} — kuchini yo'qotdi")
    for rm in changes.get("removed", []):
        lines.append(f"• {rm['label']} — olib tashlandi")
    added_count = len(changes.get("added", []))
    if added_count > 0:
        lines.append(f"(+{added_count} ta yangi band qo'shilgan)")
    return "\n".join(lines)


def refresh_doc_link(store, editorial, link: dict) -> Optional[Tuple[str, str, str]]:
    """Update a whole-act link's snapshot to current act state and archive all unit texts."""
    cid = link["canonical_id"]
    law_id = law_id_of(cid) if is_doc_link(cid) else link.get("law_id", "")
    snap = doc_snapshot(store, law_id)
    if snap is not None:
        editorial.refresh_link_snapshot(
            link["id"],
            snapshot_text=snap[0],
            snapshot_hash=snap[1],
            snapshot_status=snap[2],
        )
        archive_law_texts(store, editorial, law_id)
    return snap


def rebaseline_widened(store, editorial, law_ids) -> int:
    """
    When the corpus starts keeping more units of an act (a wider selection, not a change on Lex.uz), every whole-act
    link of that act sees "added" units and would raise a false "document_amended". For such links whose snapshotted
    units are all still present and unchanged, the current state becomes the new snapshot and the open notification
    is resolved. A link with a changed or vanished unit is left for the editor. Returns the number of links re-based.
    """
    law_ids = set(law_ids)
    rebased = 0
    for link in editorial.list_all_links():
        cid = link["canonical_id"]
        if not is_doc_link(cid) or law_id_of(cid) not in law_ids:
            continue
        try:
            old = json.loads(link.get("snapshot_text") or "{}")
        except ValueError:
            continue
        units = law_units(store, law_id_of(cid))
        if not old or any(u not in units or old[u] != f"{units[u][0]}|{units[u][1]}" for u in old):
            continue
        snap = doc_snapshot(store, law_id_of(cid))
        if snap is None or snap[1] == (link.get("snapshot_hash") or ""):
            continue
        refresh_doc_link(store, editorial, link)
        editorial.resolve_open_for_owner_link(
            owner_type=link["owner_type"],
            owner_id=link["owner_id"],
            canonical_id=cid,
            resolution="corpus_widened",
            resolved_by="system",
        )
        rebased += 1
    return rebased
