"""
Inbound webhook from the huquqplus.uz WordPress plugin (integrations/wordpress/huquqplus-rag-webhook).

The plugin only says "post N in language L changed" - it never carries article text. The sync job fetches the
post itself from the fixed huquqplus.uz REST API, so a leaked secret can at worst trigger extra re-fetches,
never inject content into the knowledge base.

Signature: X-HuquqPlus-Signature: sha256=HEX(HMAC-SHA256(secret, "<timestamp>.<raw body>")),
           X-HuquqPlus-Timestamp: unix seconds; requests older/newer than the tolerance are rejected (replay).
"""
import hashlib
import hmac
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from src.config import settings
from src.storage.sqlite_utils import connect as _sqlite_connect

SIGNATURE_HEADER = "X-HuquqPlus-Signature"
TIMESTAMP_HEADER = "X-HuquqPlus-Timestamp"
MAX_BODY_BYTES = 8192
EVENTS = ("upsert", "delete", "ping")


def sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(
    secret: str,
    timestamp: Optional[str],
    body: bytes,
    signature: Optional[str],
    now: Optional[float] = None,
    tolerance_s: int = 300,
) -> bool:
    if not secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs((time.time() if now is None else now) - ts) > tolerance_s:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature.strip())


class WebhookQueue:
    """Durable queue of change events; drained by the huquqplus sync job (deduplicated by event_id)."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or (Path(settings.STORAGE_DIR) / "huquqplus.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _sqlite_connect(self.db_path, timeout=30.0) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS webhook_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event TEXT NOT NULL,
                    post_id INTEGER NOT NULL,
                    lang TEXT NOT NULL,
                    modified_gmt TEXT,
                    received_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    processed_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_webhook_events_status ON webhook_events(status, id)")

    def enqueue(self, event_id: str, event: str, post_id: int, lang: str, modified_gmt: str = "") -> bool:
        """Returns False when the event was already received (plugin retry or replay inside the tolerance window)."""
        with _sqlite_connect(self.db_path, timeout=30.0) as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO webhook_events (event_id, event, post_id, lang, modified_gmt, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, event, post_id, lang, modified_gmt, datetime.now(timezone.utc).isoformat()),
            )
            return cur.rowcount == 1

    def pending(self, limit: int = 100) -> List[Dict]:
        with _sqlite_connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = lambda c, r: {d[0]: r[i] for i, d in enumerate(c.description)}
            return conn.execute(
                "SELECT * FROM webhook_events WHERE status = 'pending' ORDER BY id LIMIT ?", (limit,)
            ).fetchall()

    def mark_done(self, row_id: int) -> None:
        self._finish(row_id, "done", None)

    def mark_failed(self, row_id: int, error: str, max_attempts: int = 5) -> None:
        with _sqlite_connect(self.db_path, timeout=30.0) as conn:
            conn.execute(
                "UPDATE webhook_events SET attempts = attempts + 1, last_error = ?, "
                "status = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE 'pending' END WHERE id = ?",
                (error[:500], max_attempts, row_id),
            )

    def _finish(self, row_id: int, status: str, error: Optional[str]) -> None:
        with _sqlite_connect(self.db_path, timeout=30.0) as conn:
            conn.execute(
                "UPDATE webhook_events SET status = ?, last_error = ?, processed_at = ? WHERE id = ?",
                (status, error, datetime.now(timezone.utc).isoformat(), row_id),
            )

    def stats(self) -> Dict[str, int]:
        with _sqlite_connect(self.db_path, timeout=30.0) as conn:
            return {s: n for s, n in conn.execute("SELECT status, COUNT(*) FROM webhook_events GROUP BY status")}
