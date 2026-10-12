"""
API Key Management and Usage Tracking for Third-Party Integrations.
"""
import hashlib
import logging
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from src.config import settings
from src.storage.sqlite_utils import connect as _sqlite_connect

logger = logging.getLogger(__name__)


class ApiKeyRecord(BaseModel):
    key_id: str
    name: str
    key_prefix: str
    rate_limit_per_min: int
    total_requests: int
    created_at: float
    is_active: bool
    last_used_at: Optional[float] = None


class ApiKeyManager:
    """Manages API keys for external developers, Telegram bots, and mobile apps."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or (Path(settings.STORAGE_DIR) / "api_keys.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        return _sqlite_connect(self.db_path)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    key_hash TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    key_prefix TEXT NOT NULL,
                    rate_limit_per_min INTEGER NOT NULL DEFAULT 60,
                    total_requests INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    last_used_at REAL
                );
            """)
            conn.commit()

        # Seed a default demo developer key if none exist
        if not self.list_keys():
            self.create_key("Birlamchi Hamkor / Telegram Bot", rate_limit=120)

    @staticmethod
    def _hash_key(api_key: str) -> str:
        return hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()

    def create_key(self, name: str, rate_limit: int = 60) -> Dict[str, str]:
        """Generates a secure API key and stores its hash."""
        raw_token = secrets.token_urlsafe(32)
        full_key = f"incl_{raw_token}"
        key_id = f"key_{secrets.token_hex(6)}"
        key_hash = self._hash_key(full_key)
        prefix = f"{full_key[:9]}...{full_key[-4:]}"

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO api_keys (key_id, key_hash, name, key_prefix, rate_limit_per_min, total_requests, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, 0, ?, 1)
            """, (key_id, key_hash, name, prefix, rate_limit, time.time()))
            conn.commit()

        return {
            "key_id": key_id,
            "name": name,
            "api_key": full_key,
            "key_prefix": prefix,
            "rate_limit_per_min": rate_limit,
        }

    def validate_key(self, api_key: str) -> Optional[ApiKeyRecord]:
        """Validates key and increments total request counter."""
        if not api_key:
            return None
        key_hash = self._hash_key(api_key)
        now = time.time()
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT key_id, name, key_prefix, rate_limit_per_min, total_requests, created_at, is_active, last_used_at
                FROM api_keys WHERE key_hash = ? AND is_active = 1
            """, (key_hash,))
            row = c.fetchone()
            if not row:
                return None

            key_id = row[0]
            # Increment request counter
            conn.execute("""
                UPDATE api_keys 
                SET total_requests = total_requests + 1, last_used_at = ?
                WHERE key_id = ?
            """, (now, key_id))
            conn.commit()

            return ApiKeyRecord(
                key_id=row[0],
                name=row[1],
                key_prefix=row[2],
                rate_limit_per_min=row[3],
                total_requests=row[4] + 1,
                created_at=row[5],
                is_active=bool(row[6]),
                last_used_at=now,
            )

    def list_keys(self) -> List[ApiKeyRecord]:
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT key_id, name, key_prefix, rate_limit_per_min, total_requests, created_at, is_active, last_used_at
                FROM api_keys ORDER BY created_at DESC
            """)
            return [
                ApiKeyRecord(
                    key_id=row[0],
                    name=row[1],
                    key_prefix=row[2],
                    rate_limit_per_min=row[3],
                    total_requests=row[4],
                    created_at=row[5],
                    is_active=bool(row[6]),
                    last_used_at=row[7],
                )
                for row in c.fetchall()
            ]

    def revoke_key(self, key_id: str) -> bool:
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("UPDATE api_keys SET is_active = 0 WHERE key_id = ?", (key_id,))
            conn.commit()
            return c.rowcount > 0


api_key_manager = ApiKeyManager()
