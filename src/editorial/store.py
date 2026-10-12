"""SQLite storage for the editorial module (curated answers, links, notifications)."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config import settings
from src.storage.sqlite_utils import connect as sqlite_connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EditorialStore:
    """SQLite-backed store for curated answers, legal links and change notifications."""

    _initialized: set = set()   # schema setup runs once per database file, not on every request

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or (Path(settings.STORAGE_DIR) / "editorial.db"))
        key = str(self.db_path.resolve())
        if key not in self._initialized or not self.db_path.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
            self._initialized.add(key)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite_connect(self.db_path, timeout=60.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 60000")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("PRAGMA journal_mode = WAL;")
            c.execute("PRAGMA synchronous = NORMAL;")
            c.execute("""
                CREATE TABLE IF NOT EXISTS curated_answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    alt_questions TEXT NOT NULL DEFAULT '[]',
                    answer_md TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT 'uz',
                    category TEXT NOT NULL DEFAULT 'general',
                    status TEXT NOT NULL DEFAULT 'draft',
                    author TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS curated_answer_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    answer_id INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    snapshot TEXT NOT NULL,
                    editor TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    at TEXT NOT NULL
                );
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS legal_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    law_id TEXT NOT NULL DEFAULT '',
                    article_label TEXT NOT NULL DEFAULT '',
                    snapshot_text TEXT NOT NULL DEFAULT '',
                    snapshot_hash TEXT NOT NULL DEFAULT '',
                    snapshot_status TEXT NOT NULL DEFAULT 'active',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    verified_at TEXT
                );
            """)
            c.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_legal_links_owner_canonical
                ON legal_links (owner_type, owner_id, canonical_id);
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    old_hash TEXT NOT NULL DEFAULT '',
                    new_hash TEXT NOT NULL DEFAULT '',
                    old_text TEXT NOT NULL DEFAULT '',
                    new_text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    resolution TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolved_by TEXT
                );
            """)
            # De-duplication is "one open notification per (owner, norm)" plus the link's acknowledged_marker,
            # not a unique (owner, norm, new_hash) key: that key silently swallowed a real amendment whenever a
            # norm returned to an earlier wording (A -> B -> A -> B).
            c.execute("DROP INDEX IF EXISTS ux_notifications_dedup;")
            c.execute("""
                CREATE INDEX IF NOT EXISTS ix_notifications_owner_link
                ON notifications (owner_type, owner_id, canonical_id, status);
            """)
            link_columns = {r[1] for r in c.execute("PRAGMA table_info(legal_links)")}
            if "acknowledged_marker" not in link_columns:
                # last change marker an editor has already decided on (kept / unpublished): not re-reported
                c.execute("ALTER TABLE legal_links ADD COLUMN acknowledged_marker TEXT NOT NULL DEFAULT ''")
            conn.commit()

    # -- answers --------------------------------------------------------------------------------
    def create_answer(self, *, question: str, alt_questions: list, answer_md: str,
                      language: str, category: str, author: str) -> dict:
        now = _now()
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO curated_answers
                    (question, alt_questions, answer_md, language, category, status, author, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'draft', ?, 1, ?, ?)
            """, (question, json.dumps(alt_questions, ensure_ascii=False), answer_md,
                  language, category, author, now, now))
            aid = c.lastrowid
            conn.commit()
        answer = self.get_answer(aid)
        self.add_history(aid, 1, answer, author, "create")
        return answer

    def get_answer(self, answer_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM curated_answers WHERE id = ?", (answer_id,)).fetchone()
            return self._row_to_answer(row) if row else None

    def list_answers(self, *, status: Optional[str] = None, q: Optional[str] = None,
                     limit: int = 50, offset: int = 0) -> tuple[list, int]:
        clauses, params = [], []
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if q:
            clauses.append("(question LIKE ? OR answer_md LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM curated_answers {where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM curated_answers {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            return [self._row_to_answer(r) for r in rows], total

    def update_answer(self, answer_id: int, fields: dict, *, editor: str = "", action: str = "edit") -> Optional[dict]:
        allowed = {"question", "alt_questions", "answer_md", "language", "category", "status"}
        sets, params = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "alt_questions" and isinstance(v, list):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"{k} = ?")
            params.append(v)
        if not sets:
            return self.get_answer(answer_id)
        sets.append("version = version + 1")
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(answer_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE curated_answers SET {', '.join(sets)} WHERE id = ?", params)
            conn.commit()
        answer = self.get_answer(answer_id)
        if answer:
            self.add_history(answer_id, answer["version"], answer, editor, action)
        return answer

    def delete_answer(self, answer_id: int, *, resolved_by: str = "") -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM curated_answers WHERE id = ?", (answer_id,))
            conn.execute("DELETE FROM legal_links WHERE owner_type = 'curated' AND owner_id = ?", (str(answer_id),))
            # nothing is left to review: do not leave orphaned open notifications in the inbox
            conn.execute("""
                UPDATE notifications SET status = 'resolved', resolution = 'answer_deleted', resolved_at = ?,
                    resolved_by = ?
                WHERE owner_type = 'curated' AND owner_id = ? AND status = 'open'
            """, (_now(), resolved_by, str(answer_id)))
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _row_to_answer(row: sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["alt_questions"] = json.loads(d.get("alt_questions") or "[]")
        except Exception:
            d["alt_questions"] = []
        return d

    # -- history ---------------------------------------------------------------------------------
    def add_history(self, answer_id: int, version: int, snapshot: dict, editor: str, action: str) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO curated_answer_history (answer_id, version, snapshot, editor, action, at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (answer_id, version, json.dumps(snapshot, ensure_ascii=False), editor or "", action, _now()))
            conn.commit()

    def get_history(self, answer_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT version, snapshot, editor, action, at FROM curated_answer_history
                WHERE answer_id = ? ORDER BY version ASC
            """, (answer_id,)).fetchall()
            return [dict(r) for r in rows]

    # -- legal links -----------------------------------------------------------------------------
    def add_link(self, *, owner_type: str, owner_id: str, canonical_id: str, law_id: str,
                 article_label: str, snapshot_text: str, snapshot_hash: str,
                 snapshot_status: str, note: str = "") -> dict:
        now = _now()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO legal_links
                    (owner_type, owner_id, canonical_id, law_id, article_label,
                     snapshot_text, snapshot_hash, snapshot_status, note, created_at, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_type, owner_id, canonical_id) DO UPDATE SET
                    law_id = excluded.law_id,
                    article_label = excluded.article_label,
                    snapshot_text = excluded.snapshot_text,
                    snapshot_hash = excluded.snapshot_hash,
                    snapshot_status = excluded.snapshot_status,
                    note = excluded.note,
                    verified_at = excluded.verified_at,
                    acknowledged_marker = ''
            """, (owner_type, owner_id, canonical_id, law_id, article_label,
                  snapshot_text, snapshot_hash, snapshot_status, note, now, now))
            conn.commit()
            row = conn.execute("""
                SELECT * FROM legal_links WHERE owner_type = ? AND owner_id = ? AND canonical_id = ?
            """, (owner_type, owner_id, canonical_id)).fetchone()
            return dict(row)

    def refresh_link_snapshot(self, link_id: int, *, snapshot_text: str, snapshot_hash: str, snapshot_status: str) -> None:
        with self._conn() as conn:
            conn.execute("""
                UPDATE legal_links SET snapshot_text = ?, snapshot_hash = ?,
                    snapshot_status = ?, verified_at = ?, acknowledged_marker = '' WHERE id = ?
            """, (snapshot_text, snapshot_hash, snapshot_status, _now(), link_id))
            conn.commit()

    def acknowledge_link(self, *, owner_type: str, owner_id: str, canonical_id: str, marker: str) -> None:
        with self._conn() as conn:
            conn.execute("""
                UPDATE legal_links SET acknowledged_marker = ?
                WHERE owner_type = ? AND owner_id = ? AND canonical_id = ?
            """, (marker, owner_type, owner_id, canonical_id))
            conn.commit()

    def remove_link(self, *, owner_type: str, owner_id: str, canonical_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("""
                DELETE FROM legal_links WHERE owner_type = ? AND owner_id = ? AND canonical_id = ?
            """, (owner_type, owner_id, canonical_id))
            conn.commit()
            return cur.rowcount > 0

    def list_links(self, *, owner_type: str, owner_id: str) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM legal_links WHERE owner_type = ? AND owner_id = ? ORDER BY id ASC
            """, (owner_type, owner_id)).fetchall()
            return [dict(r) for r in rows]

    def list_all_links(self, *, owner_type: Optional[str] = None) -> list:
        with self._conn() as conn:
            if owner_type:
                rows = conn.execute("SELECT * FROM legal_links WHERE owner_type = ? ORDER BY id ASC",
                                    (owner_type,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM legal_links ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def delete_links_of_owner(self, *, owner_type: str, owner_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM legal_links WHERE owner_type = ? AND owner_id = ?",
                         (owner_type, owner_id))
            conn.commit()

    # -- notifications ----------------------------------------------------------------------------
    def create_notification(self, *, kind: str, owner_type: str, owner_id: str, canonical_id: str,
                            old_hash: str, new_hash: str, old_text: str, new_text: str) -> Optional[dict]:
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            already_open = conn.execute("""
                SELECT id FROM notifications
                WHERE owner_type = ? AND owner_id = ? AND canonical_id = ? AND status = 'open'
            """, (owner_type, owner_id, canonical_id)).fetchone()
            if already_open:
                # the editor has not decided yet: keep one card, but show the latest wording of the norm
                conn.execute("""
                    UPDATE notifications SET kind = ?, new_hash = ?, new_text = ? WHERE id = ? AND new_hash != ?
                """, (kind, new_hash or "", new_text or "", already_open[0], new_hash or ""))
                conn.commit()
                return None
            cur = conn.execute("""
                INSERT INTO notifications
                    (kind, owner_type, owner_id, canonical_id, old_hash, new_hash,
                     old_text, new_text, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """, (kind, owner_type, owner_id, canonical_id, old_hash or "", new_hash or "",
                  old_text or "", new_text or "", _now()))
            conn.commit()
            row = conn.execute("SELECT * FROM notifications WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row) if row else None

    def open_notifications_for_owner(self, *, owner_type: str, owner_id: str) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM notifications WHERE owner_type = ? AND owner_id = ? AND status = 'open' ORDER BY id
            """, (owner_type, owner_id)).fetchall()
            return [dict(r) for r in rows]

    def list_notifications(self, *, status: Optional[str] = None, owner_id: Optional[str] = None,
                           limit: int = 50, offset: int = 0) -> tuple[list, int]:
        clauses, params = [], []
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if owner_id:
            clauses.append("owner_id = ?")
            params.append(owner_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM notifications {where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM notifications {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows], total

    def count_open_notifications(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM notifications WHERE status = 'open'").fetchone()[0]

    def get_notification(self, notif_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,)).fetchone()
            return dict(row) if row else None

    def resolve_notification(self, notif_id: int, *, resolution: str, resolved_by: str = "") -> Optional[dict]:
        with self._conn() as conn:
            conn.execute("""
                UPDATE notifications SET status = 'resolved', resolution = ?, resolved_at = ?, resolved_by = ?
                WHERE id = ?
            """, (resolution, _now(), resolved_by, notif_id))
            conn.commit()
            row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,)).fetchone()
            return dict(row) if row else None

    def dismiss_notification(self, notif_id: int, *, resolved_by: str = "") -> Optional[dict]:
        with self._conn() as conn:
            conn.execute("""
                UPDATE notifications SET status = 'dismissed', resolved_at = ?, resolved_by = ? WHERE id = ?
            """, (_now(), resolved_by, notif_id))
            conn.commit()
            row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,)).fetchone()
            return dict(row) if row else None

    def resolve_open_for_owner_link(self, *, owner_type: str, owner_id: str,
                                    canonical_id: str, resolution: str, resolved_by: str = "") -> None:
        with self._conn() as conn:
            conn.execute("""
                UPDATE notifications SET status = 'resolved', resolution = ?, resolved_at = ?, resolved_by = ?
                WHERE owner_type = ? AND owner_id = ? AND canonical_id = ? AND status = 'open'
            """, (resolution, _now(), resolved_by, owner_type, owner_id, canonical_id))
            conn.commit()

    def resolve_open_for_owner(self, *, owner_type: str, owner_id: str,
                               resolution: str, resolved_by: str = "") -> int:
        with self._conn() as conn:
            cur = conn.execute("""
                UPDATE notifications SET status = 'resolved', resolution = ?, resolved_at = ?, resolved_by = ?
                WHERE owner_type = ? AND owner_id = ? AND status = 'open'
            """, (resolution, _now(), resolved_by, owner_type, owner_id))
            conn.commit()
            return cur.rowcount


def get_editorial_store(db_path: Optional[str] = None) -> EditorialStore:
    return EditorialStore(db_path)
