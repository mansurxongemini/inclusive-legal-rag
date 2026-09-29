import hashlib
import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np

from src.config import settings
from src.nlp.transliteration import normalize_apostrophes, cyrillic_to_latin, detect_script

logger = logging.getLogger(__name__)


class QueryCache:
    """
    Dual-Layer Intelligent Caching Engine for Legal RAG:
    - Layer 1: Canonical Normalized Hash Cache (invariant to punctuation, scripts, spaces, casing)
    - Layer 2: Vector Semantic Similarity Cache (cosine similarity >= 0.96 for rephrased queries)
    - Layer 3: Ultra-fast in-memory RAM cache for hot items
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or settings.CACHE_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = settings.CACHE_TTL_SECONDS
        self._ram_cache: Dict[str, Tuple[float, dict]] = {}
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_cache (
                    cache_key TEXT PRIMARY KEY,
                    canonical_query TEXT,
                    language TEXT,
                    mode TEXT,
                    vector_blob BLOB,
                    response_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
            """)
            # Migration check: ensure new columns exist if table was previously created
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(query_cache)")
            cols = {col[1] for col in cursor.fetchall()}
            for new_col, col_type in [
                ("canonical_query", "TEXT"),
                ("language", "TEXT"),
                ("mode", "TEXT"),
                ("vector_blob", "BLOB"),
            ]:
                if new_col not in cols:
                    try:
                        conn.execute(f"ALTER TABLE query_cache ADD COLUMN {new_col} {col_type};")
                    except Exception:
                        pass
            conn.commit()

    @classmethod
    def canonicalize_query(cls, query: str) -> str:
        """
        Normalizes query text to be invariant to:
        - Punctuation (.,?!:;'"-–—()[]{}/\)
        - Apostrophes (', ‘, ’, `, ʻ, ʼ)
        - Script (transliterates Uzbek Cyrillic -> Latin)
        - Multiple spaces, newlines, tabs
        - Lowercasing
        """
        q = normalize_apostrophes(query).strip().lower()
        if detect_script(q) == "cyrillic":
            q = cyrillic_to_latin(q)
        # Strip all punctuation and special characters, keeping alphanumeric and spaces
        q = re.sub(r"[^\w\s]", " ", q)
        return " ".join(q.split())

    def _make_key(self, query: str, language: str, mode: str) -> str:
        canonical = self.canonicalize_query(query)
        raw = f"{canonical}|{language}|{mode}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, query: str, language: str, mode: str) -> Optional[dict]:
        """Layer 1: Canonical Normalized Cache Lookup (sub-millisecond)."""
        key = self._make_key(query, language, mode)
        now = time.time()

        # 1. In-memory RAM lookup
        if key in self._ram_cache:
            created_at, resp = self._ram_cache[key]
            if now - created_at < self.ttl:
                return resp
            else:
                del self._ram_cache[key]

        # 2. SQLite lookup
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT response_json, created_at FROM query_cache WHERE cache_key = ?", (key,))
            row = cursor.fetchone()
            if row:
                resp_json, created_at = row
                if now - created_at < self.ttl:
                    data = json.loads(resp_json)
                    if len(self._ram_cache) < 512:
                        self._ram_cache[key] = (created_at, data)
                    return data
                else:
                    cursor.execute("DELETE FROM query_cache WHERE cache_key = ?", (key,))
                    conn.commit()
        return None

    def get_semantic(
        self,
        query_vector: List[float],
        language: str,
        mode: str,
        threshold: float = 0.96
    ) -> Optional[dict]:
        """
        Layer 2: Semantic Vector Similarity Cache Lookup.
        Returns cached response if cosine similarity >= threshold (default 96%).
        """
        if not query_vector:
            return None

        q_vec = np.array(query_vector, dtype=np.float32)
        norm_q = np.linalg.norm(q_vec)
        if norm_q > 0:
            q_vec = q_vec / norm_q

        now = time.time()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT response_json, vector_blob, created_at 
                FROM query_cache 
                WHERE language = ? AND mode = ? AND vector_blob IS NOT NULL
                ORDER BY created_at DESC LIMIT 500
            """, (language, mode))
            rows = cursor.fetchall()

            for resp_json, vec_blob, created_at in rows:
                if now - created_at >= self.ttl:
                    continue
                if not vec_blob:
                    continue
                c_vec = np.frombuffer(vec_blob, dtype=np.float32)
                if len(c_vec) != len(q_vec):
                    continue
                norm_c = np.linalg.norm(c_vec)
                if norm_c > 0:
                    c_vec = c_vec / norm_c
                sim = float(np.dot(q_vec, c_vec))
                if sim >= threshold:
                    data = json.loads(resp_json)
                    data["cache_type"] = "semantic"
                    data["semantic_similarity"] = round(sim, 3)
                    return data
        return None

    def set(
        self,
        query: str,
        language: str,
        mode: str,
        data: dict,
        vector: Optional[List[float]] = None
    ):
        """Stores query response with canonical key and optional dense vector embedding."""
        answer = data.get("answer", "").strip()
        # Never cache empty, broken, or truncated answers
        if len(answer) < 300 or answer.startswith("---") or answer.startswith("*Eslatma:"):
            return

        canonical = self.canonicalize_query(query)
        key = self._make_key(query, language, mode)
        now = time.time()

        vec_blob = None
        if vector:
            vec_blob = np.array(vector, dtype=np.float32).tobytes()

        # Update RAM cache
        if len(self._ram_cache) < 512:
            self._ram_cache[key] = (now, data)

        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO query_cache (
                    cache_key, canonical_query, language, mode, vector_blob, response_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (key, canonical, language, mode, vec_blob, json.dumps(data), now))
            conn.commit()

    def clear(self):
        """Clears all cached queries."""
        self._ram_cache.clear()
        with self._get_conn() as conn:
            conn.execute("DELETE FROM query_cache;")
            conn.commit()
