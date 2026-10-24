import copy
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Callable, List, Optional, Tuple
import numpy as np

from src.config import settings
from src.storage.sqlite_utils import connect as _sqlite_connect
from src.nlp.transliteration import normalize_apostrophes, cyrillic_to_latin, detect_script

logger = logging.getLogger(__name__)

# Candidate rows a semantic lookup compares against (the newest ones of the language/mode)
SEMANTIC_CANDIDATES = 500


class QueryCache:
    """
    Dual-Layer Intelligent Caching Engine for Legal RAG:
    - Layer 1: Canonical Normalized Hash Cache (invariant to punctuation, scripts, spaces, casing)
    - Layer 2: Vector Semantic Similarity Cache (cosine similarity above a caller-chosen threshold for rephrased queries)
    - Layer 3: Ultra-fast in-memory RAM cache for hot items (LRU)

    Every method opens its own SQLite connection and the RAM layer is guarded by a lock, so the cache can be used from
    worker threads (the answering pipeline calls it through asyncio.to_thread: a lookup must not stall the event loop).
    """

    RAM_MAX_ITEMS = 512

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or settings.CACHE_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = settings.CACHE_TTL_SECONDS
        self._ram_cache: "OrderedDict[str, Tuple[float, dict]]" = OrderedDict()     # least recently used first
        self._lock = threading.Lock()                                               # guards _ram_cache and _stats
        self._stats = {
            "canonical_hits": 0,
            "semantic_hits": 0,
            "misses": 0,
            "saved_tokens_est": 0
        }
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        return _sqlite_connect(self.db_path)

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
                    except Exception as e:
                        logger.warning(f"query_cache migration of column {new_col} failed: {e}")
            # the semantic lookup reads the newest rows of one language/mode; created_at also serves the expiry purge
            conn.execute("CREATE INDEX IF NOT EXISTS idx_query_cache_lang_mode ON query_cache (language, mode, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_query_cache_created ON query_cache (created_at)")
            conn.commit()

    @classmethod
    def canonicalize_query(cls, query: str) -> str:
        r"""
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

    def _ram_put(self, key: str, created_at: float, data: dict) -> None:
        """Stores (or replaces) a hot entry; once RAM_MAX_ITEMS is exceeded the least recently used one is dropped, so
        a full cache neither keeps serving a replaced answer nor refuses new entries."""
        snapshot = copy.deepcopy(data)
        with self._lock:
            self._ram_cache[key] = (created_at, snapshot)
            self._ram_cache.move_to_end(key)
            while len(self._ram_cache) > self.RAM_MAX_ITEMS:
                self._ram_cache.popitem(last=False)

    def _count(self, hit_kind: str, data: dict) -> None:
        with self._lock:
            self._stats[hit_kind] += 1
            self._stats["saved_tokens_est"] += len(data.get("answer", "").split()) * 2

    def get(self, query: str, language: str, mode: str) -> Optional[dict]:
        """Layer 1: Canonical Normalized Cache Lookup (sub-millisecond)."""
        key = self._make_key(query, language, mode)
        now = time.time()

        # 1. In-memory RAM lookup
        with self._lock:
            hot = self._ram_cache.get(key)
            if hot is not None:
                created_at, resp = hot
                if now - created_at < self.ttl:
                    self._ram_cache.move_to_end(key)
                    self._stats["canonical_hits"] += 1
                    resp = copy.deepcopy(resp)
                    resp["cache_type"] = "exact_ram"
                    return resp
                del self._ram_cache[key]

        # 2. SQLite lookup
        with self._get_conn() as conn:
            row = conn.execute("SELECT response_json, created_at FROM query_cache WHERE cache_key = ?", (key,)).fetchone()
            if row:
                resp_json, created_at = row
                if now - created_at < self.ttl:
                    data = json.loads(resp_json)
                    data["cache_type"] = "exact_disk"
                    self._count("canonical_hits", data)
                    self._ram_put(key, created_at, data)
                    return data
                conn.execute("DELETE FROM query_cache WHERE cache_key = ?", (key,))
                conn.commit()
        return None

    def get_semantic(
        self,
        query_vector: List[float],
        language: str,
        mode: str,
        threshold: float = 0.93,
        accept: Optional[Callable[[dict], bool]] = None,
    ) -> Optional[dict]:
        """
        Layer 2: Semantic Vector Similarity Cache Lookup.
        Returns the most similar cached response whose cosine similarity is >= threshold (default 93%) and which
        `accept` does not veto. Only the vectors of the newest SEMANTIC_CANDIDATES rows are read and compared in one
        matrix product; the (large) response of a row is read only when that row is a hit.
        """
        if not query_vector:
            return None

        q_vec = np.array(query_vector, dtype=np.float32)
        norm_q = np.linalg.norm(q_vec)
        if norm_q > 0:
            q_vec = q_vec / norm_q

        now = time.time()
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT cache_key, vector_blob FROM query_cache "
                "WHERE language = ? AND mode = ? AND vector_blob IS NOT NULL AND created_at > ? "
                "ORDER BY created_at DESC LIMIT ?",
                (language, mode, now - self.ttl, SEMANTIC_CANDIDATES),
            ).fetchall()

            keys, vectors = [], []
            for cache_key, blob in rows:
                vec = np.frombuffer(blob, dtype=np.float32) if blob else None
                if vec is not None and len(vec) == len(q_vec):
                    keys.append(cache_key)
                    vectors.append(vec)
            if not vectors:
                return None

            matrix = np.vstack(vectors)
            norms = np.linalg.norm(matrix, axis=1)
            norms[norms == 0] = 1.0
            similarities = (matrix / norms[:, None]) @ q_vec

            for idx in np.argsort(-similarities):
                sim = float(similarities[idx])
                if sim < threshold:
                    break
                row = conn.execute("SELECT response_json FROM query_cache WHERE cache_key = ?", (keys[idx],)).fetchone()
                if not row:
                    continue
                data = json.loads(row[0])
                # a near-identical question may still concern another beneficiary group ("I guruh" vs
                # "II guruh"); the caller can veto such hits
                if accept is not None and not accept(data):
                    continue
                data["cache_type"] = "semantic"
                data["semantic_similarity"] = round(sim, 3)
                self._count("semantic_hits", data)
                return data
        return None

    def get_stats(self) -> dict:
        """Returns live cache efficiency and token savings metrics."""
        with self._get_conn() as conn:
            count = conn.execute("SELECT count(*) FROM query_cache;").fetchone()[0]
        with self._lock:
            return {
                "total_cached_queries": count,
                "ram_cache_hot_items": len(self._ram_cache),
                "canonical_exact_hits": self._stats["canonical_hits"],
                "semantic_similarity_hits": self._stats["semantic_hits"],
                "estimated_saved_tokens": self._stats["saved_tokens_est"],
            }

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

        self._ram_put(key, now, data)

        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO query_cache (
                    cache_key, canonical_query, language, mode, vector_blob, response_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (key, canonical, language, mode, vec_blob, json.dumps(data), now))
            conn.commit()

    def purge_expired(self) -> int:
        """Deletes the entries older than the TTL (disk and RAM) and returns how many disk rows were removed. Without it
        a row that is never asked for again stays in the file for ever."""
        cutoff = time.time() - self.ttl
        with self._lock:
            for key in [k for k, (created_at, _) in self._ram_cache.items() if created_at < cutoff]:
                del self._ram_cache[key]
        with self._get_conn() as conn:
            removed = conn.execute("DELETE FROM query_cache WHERE created_at < ?", (cutoff,)).rowcount
            conn.commit()
        return removed

    def clear(self):
        """Flushes both the RAM cache and the persistent SQLite cache (call after any corpus change)."""
        with self._lock:
            self._ram_cache.clear()
        with self._get_conn() as conn:
            conn.execute("DELETE FROM query_cache;")
            conn.commit()
