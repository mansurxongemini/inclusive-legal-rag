"""
Document-level legal links.

Most Lex.uz references in Huquq+ articles point at a whole act (no article anchor). Such a reference is watched as
a link to `law:<law_id>`: its snapshot is the state (hash + status) of every unit of the act that is in the corpus,
so any amendment of those units raises one "document_amended" notification listing what changed.
"""
import hashlib
import json
from typing import Dict, Optional, Tuple

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


def law_label(store, law_id: str) -> str:
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


def doc_change_summary(store, law_id: str, old_state_json: str) -> str:
    """Human-readable list of the units that changed since the snapshot (shown in the notification card)."""
    try:
        old = json.loads(old_state_json or "{}")
    except ValueError:
        old = {}
    units = law_units(store, law_id)
    changed = [label for cid, (h, st, label) in units.items() if cid in old and old[cid] != f"{h}|{st}"]
    added = [label for cid, (_, _, label) in units.items() if cid not in old]
    removed = [cid for cid in old if cid not in units]
    lines = [f"Hujjat: {law_label(store, law_id)}"]
    if changed:
        lines.append("O'zgartirilgan bandlar: " + ", ".join(sorted(changed)[:40]))
    if added:
        lines.append("Qo'shilgan bandlar: " + ", ".join(sorted(added)[:40]))
    if removed:
        lines.append("Olib tashlangan bandlar: " + ", ".join(sorted(removed)[:40]))
    return "\n".join(lines)
