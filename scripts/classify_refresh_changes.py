#!/usr/bin/env python3
"""
After a refresh: which open "document/norm amended" notifications are a re-parse only, and which carry new legal text.

A parser change (for example points that followed a repealed point becoming units of their own) makes refresh flag every
touched act as amended, and every Huquq+ post or curated answer linked to it is held back until an editor resolves the
notification. This compares the sentences of each act before and after: an act whose sentences are exactly the same
(none added, none removed: a repealed point or a deleted paragraph only removes text) changed only its unit boundaries.
Only the notifications this refresh opened are looked at (those absent from the --before store's editorial.db): a card
an earlier refresh opened for a real amendment is never closed here. --resolve closes the re-parse-only ones the way an
editor's "keep" does (the link snapshot is refreshed, so the next watch run does not open them again); the others stay
open for the editor.

--keep-untouched also closes a card with new text when its post or answer cannot be affected: the units of the act
that changed are known (before/after text of each unit), and the post neither names one of them ("28-modda",
"29-band") nor contains any three-word run around a changed word, old or new ("oyning 16-sanasiga qadar" when the
deadline became the 26th; "yoki jinoyat fuqarolik" when "konstitutsiyaviy" was added to a list of courts). The resolution note lists what changed, so the editor can audit it.
A post that names a changed unit, or a card whose owner text cannot be read, stays open.

  python scripts/classify_refresh_changes.py --before data/backups/<backup>/ --after data/store
  python scripts/classify_refresh_changes.py --before ... --after data/store --resolve [--keep-untouched]
"""
import argparse
import collections
import difflib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESOLUTION = ("Re-parse only: the act's units were split differently; no sentence of the act changed (checked by "
              "scripts/classify_refresh_changes.py). No editorial action needed.")


def sentences(text: str) -> Set[str]:
    t = re.sub(r"\s+", " ", re.sub(r"[ʻʼ‘’`]", "'", text or ""))
    return {s.strip(" .;:,").lower() for s in re.split(r"(?<=[.;:])\s+", t) if len(s.strip()) > 3}


def act_of(canonical_id: str) -> str:
    if canonical_id.startswith("law:"):
        return canonical_id[4:]
    return re.sub(r"_(?:a\d+_)?(?:p|art)_[\d_]+$|_preamble$", "", canonical_id)


def sentences_by_act(store_dir: Path) -> Dict[str, Set[str]]:
    con = sqlite3.connect(f"file:{store_dir / 'legal_rag.db'}?mode=ro", uri=True)
    out: Dict[str, Set[str]] = collections.defaultdict(set)
    for _cid, raw in con.execute("SELECT canonical_id, json_data FROM articles_metadata"):
        d = json.loads(raw)
        out[d["metadata"]["law_id"]] |= sentences((d.get("translations") or {}).get("uz"))
    con.close()
    return out


def unit_texts(store_dir: Path, law_id: str) -> Dict[str, tuple]:
    """{canonical_id: (Uzbek text, article/point label)} of one act."""
    con = sqlite3.connect(f"file:{store_dir / 'legal_rag.db'}?mode=ro", uri=True)
    out = {}
    for cid, raw in con.execute("SELECT canonical_id, json_data FROM articles_metadata "
                                "WHERE json_extract(json_data, '$.metadata.law_id') = ?", (law_id,)):
        d = json.loads(raw)
        out[cid] = ((d.get("translations") or {}).get("uz") or "", d["metadata"].get("article_number") or "")
    con.close()
    return out


def words(text: str) -> List[str]:
    return re.findall(r"[\w']+", re.sub(r"[ʻʼ‘’`]", "'", text or "").lower())


def changed_runs(old: str, new: str, size: int = 3) -> Set[str]:
    """Every run of `size` words, of the old text and of the new one, that contains a changed word."""
    a, b = words(old), words(new)
    runs: Set[str] = set()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        for seq, lo, hi in ((a, i1, i2), (b, j1, j2)):
            # windows that cover the change; an insertion (lo == hi) is covered by the words around it
            for start in range(max(0, lo - size + 1), min(len(seq) - size, max(lo, hi - 1)) + 1):
                runs.add(" ".join(seq[start:start + size]))
    return runs


def changed_units(before: Dict[str, tuple], after: Dict[str, tuple]) -> Dict[str, tuple]:
    """{canonical_id: (label, word runs around every change)} of the units whose text differs."""
    out = {}
    for cid in set(before) | set(after):
        old, new = before.get(cid, ("", "")), after.get(cid, ("", ""))
        if old[0] != new[0]:
            out[cid] = (new[1] or old[1], changed_runs(old[0], new[0]))
    return out


def mentions(text: str, changes: Dict[str, tuple]) -> bool:
    """True when the text names a changed unit ("28-modda", "29-band") or repeats words around a change."""
    joined = f" {' '.join(words(text))} "
    for label, runs in changes.values():
        m = re.match(r"(\d+(?:[-.]\d+)?)\s*-?\s*(modda|band|qism|bob)", label.lower())
        if m and re.search(rf"(?<![\d.]){re.escape(m.group(1))}\s*-\s*{m.group(2)}", text.lower()):
            return True
        if any(f" {r} " in joined for r in runs):
            return True
    return False


def classify(before: Dict[str, Set[str]], after: Dict[str, Set[str]], notifications) -> Dict[str, list]:
    """notifications: (id, kind, canonical_id). {'structural': [ids], 'content': [(id, act, added and removed sentences)]}."""
    out: Dict[str, list] = {"structural": [], "content": []}
    for nid, _kind, cid in notifications:
        act = act_of(cid)
        added = after.get(act, set()) - before.get(act, set())
        removed = before.get(act, set()) - after.get(act, set())
        if added or removed:
            out["content"].append((nid, act, sorted(f"+ {x}" for x in added)[:2] + sorted(f"- {x}" for x in removed)[:2]))
        else:
            out["structural"].append(nid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True, help="store folder before the refresh (a backup)")
    ap.add_argument("--after", required=True, help="store folder after the refresh")
    ap.add_argument("--resolve", action="store_true", help="resolve the re-parse-only notifications in --after")
    ap.add_argument("--keep-untouched", action="store_true",
                    help="with --resolve: also close cards whose post names no changed unit and quotes no changed sentence")
    args = ap.parse_args()
    after_dir, before_dir = Path(args.after), Path(args.before)
    old_ids = set()
    if (before_dir / "editorial.db").exists():
        con = sqlite3.connect(f"file:{before_dir / 'editorial.db'}?mode=ro", uri=True)
        old_ids = {r[0] for r in con.execute("SELECT id FROM notifications")}
        con.close()
    con = sqlite3.connect(f"file:{after_dir / 'editorial.db'}?mode=ro", uri=True)
    open_rows = [r for r in con.execute("SELECT id, kind, canonical_id FROM notifications WHERE status = 'open' "
                                        "AND kind IN ('document_amended', 'norm_amended')").fetchall()
                 if r[0] not in old_ids]                  # only the cards this refresh opened
    owners = dict(((r[0], (r[1], r[2])) for r in con.execute("SELECT id, owner_type, owner_id FROM notifications")))
    con.close()
    result = classify(sentences_by_act(Path(args.before)), sentences_by_act(after_dir), open_rows)
    print(f"re-parse only: {len(result['structural'])}, new text: {len(result['content'])}")
    for nid, act, new in result["content"]:
        print(f"  open #{nid} {act}: {[s[:80] for s in new]}")
    if args.resolve and result["structural"]:
        from src.editorial.service import resolve_notification_action
        from src.editorial.store import EditorialStore
        from src.storage.hybrid_store import HybridStore
        editorial, store = EditorialStore(str(after_dir / "editorial.db")), HybridStore(str(after_dir))
        for nid in result["structural"]:
            resolve_notification_action(store, editorial, editorial.get_notification(nid), action="keep",
                                        note=RESOLUTION, resolved_by="classify_refresh_changes")
        print(f"resolved {len(result['structural'])}")
    if args.resolve and args.keep_untouched and result["content"]:
        untouched = []
        for nid, act, _ in result["content"]:
            changes = changed_units(unit_texts(before_dir, act), unit_texts(after_dir, act))
            text = owner_text(after_dir, *owners[nid])
            if changes and text and not mentions(text, changes):
                labels = ", ".join(sorted({lab or cid for cid, (lab, _) in changes.items()}))
                untouched.append((nid, f"Amended on Lex.uz: {act} {labels}. The post does not name these units or "
                                       "repeat the words around a change (scripts/classify_refresh_changes.py "
                                       "--keep-untouched); kept."))
        if untouched:
            from src.editorial.service import resolve_notification_action
            from src.editorial.store import EditorialStore
            from src.storage.hybrid_store import HybridStore
            editorial, store = EditorialStore(str(after_dir / "editorial.db")), HybridStore(str(after_dir))
            for nid, note in untouched:
                resolve_notification_action(store, editorial, editorial.get_notification(nid), action="keep",
                                            note=note, resolved_by="classify_refresh_changes")
        print(f"kept as untouched: {len(untouched)}, left open: {len(result['content']) - len(untouched)}")
    return 0


def owner_text(store_dir: Path, owner_type: str, owner_id: str) -> str:
    """The text a notification protects: a Huquq+ post (its stored units) or a curated answer; '' when unknown."""
    if owner_type == "huquqplus":
        lang, _, wp_id = owner_id.partition(":")
        con = sqlite3.connect(f"file:{store_dir / 'huquqplus.db'}?mode=ro", uri=True)
        row = con.execute("SELECT unit_ids FROM hp_posts WHERE lang = ? AND wp_id = ?", (lang, wp_id)).fetchone()
        con.close()
        if not row:
            return ""
        ids = json.loads(row[0] or "[]")
        con = sqlite3.connect(f"file:{store_dir / 'legal_rag.db'}?mode=ro", uri=True)
        texts = [json.loads(r[0]).get("translations", {}).get("uz", "") for r in con.execute(
            f"SELECT json_data FROM articles_metadata WHERE canonical_id IN ({','.join('?' * len(ids))})", ids)]
        con.close()
        return "\n".join(texts)
    if owner_type == "curated":
        con = sqlite3.connect(f"file:{store_dir / 'editorial.db'}?mode=ro", uri=True)
        row = con.execute("SELECT answer_md FROM curated_answers WHERE id = ?", (owner_id,)).fetchone()
        con.close()
        return row[0] if row else ""
    return ""


if __name__ == "__main__":
    sys.exit(main())
