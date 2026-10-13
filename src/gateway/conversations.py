"""
Conversation and answer storage for the Assistant API.

SQLite database at STORAGE_DIR/assistant.db holding conversations, turns, answers and feedback.
A conversation is accessible ONLY by the same client_id AND user_ref.
"""
import json
import logging
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.config import settings
from src.storage.sqlite_utils import connect as _sqlite_connect

logger = logging.getLogger(__name__)


@dataclass
class Conversation:
    conversation_id: str
    client_id: str
    user_ref: Optional[str]
    created_at: float
    updated_at: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Turn:
    conversation_id: str
    question: str
    standalone_question: str
    answer: str
    citation_ids: List[str]
    created_at: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StoredAnswer:
    answer_id: str
    client_id: str
    user_ref: Optional[str]
    conversation_id: Optional[str]
    question: str
    answer: str
    citations_json: str
    is_refusal: bool
    latency_ms: int
    created_at: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FeedbackRecord:
    answer_id: str
    rating: str
    comment: str
    created_at: float

    def to_dict(self) -> dict:
        return asdict(self)


class ConversationStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or (Path(settings.STORAGE_DIR) / "assistant.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self):
        conn = _sqlite_connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    user_ref TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_conv_client_user ON conversations(client_id, user_ref);

                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    question TEXT NOT NULL,
                    standalone_question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    citation_ids TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_turns_conv ON turns(conversation_id, created_at);

                CREATE TABLE IF NOT EXISTS answers (
                    answer_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    user_ref TEXT,
                    conversation_id TEXT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    is_refusal INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_answers_client ON answers(client_id, created_at);

                CREATE TABLE IF NOT EXISTS feedback (
                    answer_id TEXT PRIMARY KEY REFERENCES answers(answer_id) ON DELETE CASCADE,
                    rating TEXT NOT NULL,
                    comment TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
            """)

    # -- Conversations -----------------------------------------------------------------------------------
    def get_or_create_conversation(
        self,
        conversation_id: Optional[str],
        client_id: str,
        user_ref: Optional[str],
    ) -> Tuple[Conversation, bool]:
        """
        Returns (Conversation, is_new).
        If conversation_id is provided, validates that client_id and user_ref match.
        If it doesn't exist or client_id/user_ref don't match, returns (None, False).
        If conversation_id is None, creates a brand new conversation.
        """
        now = time.time()
        if conversation_id:
            with self._conn() as conn:
                r = conn.execute(
                    "SELECT conversation_id, client_id, user_ref, created_at, updated_at FROM conversations WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
            if not r:
                return None, False
            conv = Conversation(*r)
            # A conversation is usable only by the same client_id AND user_ref
            if conv.client_id != client_id or conv.user_ref != user_ref:
                return None, False
            return conv, False

        # Create new conversation
        new_id = secrets.token_urlsafe(16)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversations (conversation_id, client_id, user_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (new_id, client_id, user_ref, now, now),
            )
        return Conversation(new_id, client_id, user_ref, now, now), True

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT conversation_id, client_id, user_ref, created_at, updated_at FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return Conversation(*r) if r else None

    def delete_conversation(self, conversation_id: str, client_id: str, user_ref: Optional[str]) -> bool:
        """Deletes that user's conversation and its turns. Must match client_id and user_ref."""
        with self._conn() as conn:
            r = conn.execute(
                "SELECT client_id, user_ref FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if not r or r[0] != client_id or r[1] != user_ref:
                return False
            conn.execute("DELETE FROM turns WHERE conversation_id = ?", (conversation_id,))
            cur = conn.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
            return cur.rowcount > 0

    # -- Turns & History ---------------------------------------------------------------------------------
    def add_turn(
        self,
        conversation_id: str,
        question: str,
        standalone_question: str,
        answer: str,
        citation_ids: List[str],
    ) -> Turn:
        now = time.time()
        cids_str = json.dumps(citation_ids)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO turns (conversation_id, question, standalone_question, answer, citation_ids, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, question, standalone_question, answer, cids_str, now),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE conversation_id = ?", (now, conversation_id))
        return Turn(conversation_id, question, standalone_question, answer, citation_ids, now)

    def get_history(self, conversation_id: str, max_turns: int = 4, max_age_hours: int = 24) -> List[Turn]:
        """Returns the last 4 turns from the last 24 h, sorted chronologically."""
        cutoff = time.time() - (max_age_hours * 3600.0)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT conversation_id, question, standalone_question, answer, citation_ids, created_at
                FROM (
                    SELECT id, conversation_id, question, standalone_question, answer, citation_ids, created_at
                    FROM turns
                    WHERE conversation_id = ? AND created_at >= ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
                """,
                (conversation_id, cutoff, max_turns),
            ).fetchall()
        out = []
        for r in rows:
            try:
                cids = json.loads(r[4])
            except Exception:
                cids = []
            out.append(Turn(r[0], r[1], r[2], r[3], cids, r[5]))
        return out

    # -- Answers -----------------------------------------------------------------------------------------
    def record_answer(
        self,
        client_id: str,
        user_ref: Optional[str],
        conversation_id: Optional[str],
        question: str,
        answer: str,
        citations_json: str,
        is_refusal: bool,
        latency_ms: int,
        answer_id: Optional[str] = None,
    ) -> StoredAnswer:
        ans_id = answer_id or secrets.token_urlsafe(16)
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO answers (answer_id, client_id, user_ref, conversation_id, question, answer, citations_json, is_refusal, latency_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ans_id, client_id, user_ref, conversation_id, question, answer, citations_json, int(is_refusal), latency_ms, now),
            )
        return StoredAnswer(ans_id, client_id, user_ref, conversation_id, question, answer, citations_json, is_refusal, latency_ms, now)

    def get_answer(self, answer_id: str) -> Optional[StoredAnswer]:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT answer_id, client_id, user_ref, conversation_id, question, answer, citations_json, is_refusal, latency_ms, created_at "
                "FROM answers WHERE answer_id = ?",
                (answer_id,),
            ).fetchone()
        if not r:
            return None
        return StoredAnswer(r[0], r[1], r[2], r[3], r[4], r[5], r[6], bool(r[7]), r[8], r[9])

    # -- Feedback ----------------------------------------------------------------------------------------
    def record_feedback(self, answer_id: str, rating: str, comment: str = "") -> FeedbackRecord:
        now = time.time()
        comment_clean = (comment or "")[:2000]
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO feedback (answer_id, rating, comment, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(answer_id) DO UPDATE SET rating = excluded.rating, comment = excluded.comment, created_at = excluded.created_at",
                (answer_id, rating, comment_clean, now),
            )
        return FeedbackRecord(answer_id, rating, comment_clean, now)

    def get_feedback(self, answer_id: str) -> Optional[FeedbackRecord]:
        with self._conn() as conn:
            r = conn.execute("SELECT answer_id, rating, comment, created_at FROM feedback WHERE answer_id = ?", (answer_id,)).fetchone()
        return FeedbackRecord(*r) if r else None

    # -- Retention Purge ---------------------------------------------------------------------------------
    def purge_older_than(self, days: int) -> Dict[str, int]:
        """Purges answers, turns, feedback and stale conversations older than `days` days."""
        if days <= 0:
            return {"feedback": 0, "answers": 0, "turns": 0, "conversations": 0}
        cutoff = time.time() - (days * 86400.0)
        with self._conn() as conn:
            # 1. Feedback for answers older than cutoff (or answers about to be deleted)
            cur_fb = conn.execute("DELETE FROM feedback WHERE created_at < ?", (cutoff,))
            fb_count = cur_fb.rowcount

            # 2. Answers
            cur_ans = conn.execute("DELETE FROM answers WHERE created_at < ?", (cutoff,))
            ans_count = cur_ans.rowcount

            # 3. Turns
            cur_turns = conn.execute("DELETE FROM turns WHERE created_at < ?", (cutoff,))
            turns_count = cur_turns.rowcount

            # 4. Conversations that haven't been updated since cutoff
            cur_conv = conn.execute(
                "DELETE FROM conversations WHERE updated_at < ? AND conversation_id NOT IN (SELECT DISTINCT conversation_id FROM turns)",
                (cutoff,),
            )
            conv_count = cur_conv.rowcount

        logger.info(
            f"Assistant store purged entries older than {days} days: "
            f"{ans_count} answers, {turns_count} turns, {fb_count} feedback, {conv_count} conversations."
        )
        return {
            "feedback": fb_count,
            "answers": ans_count,
            "turns": turns_count,
            "conversations": conv_count,
        }


_conversation_store: Optional[ConversationStore] = None


def get_conversation_store() -> ConversationStore:
    global _conversation_store
    if _conversation_store is None:
        _conversation_store = ConversationStore()
    return _conversation_store
