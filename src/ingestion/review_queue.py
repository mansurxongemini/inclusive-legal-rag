import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel
from src.config import settings
from src.storage.sqlite_utils import connect as _sqlite_connect



class ReviewQueueItem(BaseModel):
    id: Optional[int] = None
    canonical_id: str
    change_type: str  # new_article | amended_article | unreviewed_translation
    diff_summary: str
    proposed_json: str
    status: str = "pending"  # pending | approved | rejected
    created_at: Optional[str] = None


class ReviewQueue:
    """Persistent SQLite queue for human legal review before changes go live."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or settings.REVIEW_QUEUE_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = _sqlite_connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_id TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    diff_summary TEXT NOT NULL,
                    proposed_json TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

    def enqueue(self, item: ReviewQueueItem) -> int:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO review_queue (canonical_id, change_type, diff_summary, proposed_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                item.canonical_id,
                item.change_type,
                item.diff_summary,
                item.proposed_json,
                item.status,
                datetime.now(timezone.utc).isoformat(),
            ))
            conn.commit()
            return cursor.lastrowid

    def list_pending(self, limit: int = 50) -> List[ReviewQueueItem]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, canonical_id, change_type, diff_summary, proposed_json, status, created_at
                FROM review_queue
                WHERE status = 'pending'
                ORDER BY id DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [ReviewQueueItem(**dict(r)) for r in rows]

    def set_status(self, item_id: int, status: str):
        with self._get_conn() as conn:
            conn.execute("UPDATE review_queue SET status = ? WHERE id = ?", (status, item_id))
            conn.commit()
