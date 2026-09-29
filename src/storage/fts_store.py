import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from src.config import settings
from src.schema.canonical import CanonicalArticle

logger = logging.getLogger(__name__)


class SqliteFtsStore:
    """Embedded SQLite FTS5 store for BM25 full-text search and canonical article storage."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or (Path(settings.STORAGE_DIR) / "legal_rag.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=60.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 60000")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            
            # Canonical Metadata Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS articles_metadata (
                    canonical_id TEXT PRIMARY KEY,
                    json_data TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    category TEXT NOT NULL,
                    last_verified_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # FTS5 Virtual Table for BM25 Full-Text Search
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                    canonical_id UNINDEXED,
                    language,
                    article_number,
                    law_number,
                    title,
                    body,
                    tokenize = 'unicode61 remove_diacritics 2'
                );
            """)

            # Feedback Table (Section 5)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    canonical_ids TEXT,
                    rating INTEGER,
                    feedback_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            conn.commit()

    def upsert_article(self, article: CanonicalArticle):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            json_str = article.model_dump_json()

            # Upsert into articles_metadata
            cursor.execute("""
                INSERT INTO articles_metadata (
                    canonical_id, json_data, source_hash, status, category, last_verified_date, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_id) DO UPDATE SET
                    json_data = excluded.json_data,
                    source_hash = excluded.source_hash,
                    status = excluded.status,
                    category = excluded.category,
                    last_verified_date = excluded.last_verified_date,
                    updated_at = excluded.updated_at
            """, (
                article.canonical_id,
                json_str,
                article.metadata.source_hash,
                article.metadata.status.value,
                article.metadata.category,
                article.metadata.last_verified_date,
                datetime.now(timezone.utc).isoformat(),
            ))

            # Delete old FTS records for this canonical_id
            cursor.execute("DELETE FROM articles_fts WHERE canonical_id = ?", (article.canonical_id,))

            # Insert FTS records for each available non-empty translation (uz, uz_cyrl, ru, en)
            for lang, body in article.translations.items():
                if not body or not body.strip():
                    continue
                title = article.get_title(lang)
                cursor.execute("""
                    INSERT INTO articles_fts (
                        canonical_id, language, article_number, law_number, title, body
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    article.canonical_id,
                    lang,
                    article.metadata.article_number,
                    article.metadata.law_number,
                    title,
                    article.to_fts_document(lang),
                ))

            conn.commit()
            if hasattr(self, "_article_cache"):
                self._article_cache[article.canonical_id] = article

    def bm25_search(
        self,
        query: str,
        language: str = "uz",
        top_k: int = 20
    ) -> List[Dict]:
        """
        Executes BM25 search on FTS5 virtual table.
        Returns list of {canonical_id, score, rank}.
        """
        # Clean query for FTS5 (escape special chars)
        clean_terms = []
        for word in query.replace('"', '').replace("'", "").split():
            clean = "".join(c for c in word if c.isalnum() or c in "-_")
            if clean:
                clean_terms.append(f'"{clean}"*')

        if not clean_terms:
            return []

        fts_match_query = " OR ".join(clean_terms)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = []
            try:
                # 1. Try AND matching first for precise multi-term retrieval
                and_query = " AND ".join(clean_terms)
                cursor.execute("""
                    SELECT canonical_id, bm25(articles_fts, 0.0, 0.0, 10.0, 5.0, 5.0, 1.0) AS bm25_score
                    FROM articles_fts
                    WHERE articles_fts MATCH ? AND language = ?
                    ORDER BY bm25_score ASC
                    LIMIT ?
                """, (and_query, language, top_k))
                rows = list(cursor.fetchall())

                # 2. If fewer than top_k results, supplement with OR query
                if len(rows) < top_k:
                    seen_ids = {r["canonical_id"] for r in rows}
                    or_query = " OR ".join(clean_terms)
                    cursor.execute("""
                        SELECT canonical_id, bm25(articles_fts, 0.0, 0.0, 10.0, 5.0, 5.0, 1.0) AS bm25_score
                        FROM articles_fts
                        WHERE articles_fts MATCH ? AND language = ?
                        ORDER BY bm25_score ASC
                        LIMIT ?
                    """, (or_query, language, top_k * 2))
                    for r in cursor.fetchall():
                        if r["canonical_id"] not in seen_ids:
                            rows.append(r)
                            seen_ids.add(r["canonical_id"])
                            if len(rows) >= top_k:
                                break

                # 3. Fallback across all languages if still empty
                if not rows:
                    or_query = " OR ".join(clean_terms)
                    cursor.execute("""
                        SELECT canonical_id, bm25(articles_fts, 0.0, 0.0, 10.0, 5.0, 5.0, 1.0) AS bm25_score
                        FROM articles_fts
                        WHERE articles_fts MATCH ?
                        ORDER BY bm25_score ASC
                        LIMIT ?
                    """, (or_query, top_k))
                    rows = list(cursor.fetchall())

            except sqlite3.OperationalError as e:
                logger.warning(f"FTS search error: {e}, falling back to empty results")
                return []

            results = []
            for row in rows:
                raw_score = abs(row["bm25_score"])
                # Monotonic normalization: higher raw_score -> higher norm_score in [0, 1)
                norm_score = raw_score / (1.0 + raw_score) if raw_score > 0 else 0.0
                results.append({
                    "canonical_id": row["canonical_id"],
                    "score": norm_score,
                })
            return results

    def get_article(self, canonical_id: str) -> Optional[CanonicalArticle]:
        if not hasattr(self, "_article_cache"):
            self._article_cache = {}
        if canonical_id in self._article_cache:
            return self._article_cache[canonical_id]

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT json_data FROM articles_metadata WHERE canonical_id = ?", (canonical_id,))
            row = cursor.fetchone()
            if row:
                art = CanonicalArticle.model_validate_json(row["json_data"])
                if len(self._article_cache) < 2048:
                    self._article_cache[canonical_id] = art
                return art
            return None

    def get_articles_batch(self, canonical_ids: List[str]) -> Dict[str, CanonicalArticle]:
        """High-efficiency batch lookup of canonical articles with RAM caching."""
        if not canonical_ids:
            return {}
        if not hasattr(self, "_article_cache"):
            self._article_cache = {}

        result: Dict[str, CanonicalArticle] = {}
        missing_ids: List[str] = []

        for cid in canonical_ids:
            if cid in self._article_cache:
                result[cid] = self._article_cache[cid]
            else:
                missing_ids.append(cid)

        if not missing_ids:
            return result

        chunk_size = 500
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for i in range(0, len(missing_ids), chunk_size):
                chunk = missing_ids[i:i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                cursor.execute(
                    f"SELECT canonical_id, json_data FROM articles_metadata WHERE canonical_id IN ({placeholders})",
                    chunk
                )
                for row in cursor.fetchall():
                    try:
                        art = CanonicalArticle.model_validate_json(row["json_data"])
                        cid = row["canonical_id"]
                        result[cid] = art
                        if len(self._article_cache) < 2048:
                            self._article_cache[cid] = art
                    except Exception as e:
                        logger.warning(f"Error parsing canonical article {row['canonical_id']}: {e}")
        return result


    def list_articles(self, limit: int = 100, offset: int = 0) -> List[CanonicalArticle]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT json_data FROM articles_metadata
                ORDER BY canonical_id ASC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            rows = cursor.fetchall()
            return [CanonicalArticle.model_validate_json(r["json_data"]) for r in rows]

    def delete_article(self, canonical_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM articles_metadata WHERE canonical_id = ?", (canonical_id,))
            cursor.execute("DELETE FROM articles_fts WHERE canonical_id = ?", (canonical_id,))
            conn.commit()
            if hasattr(self, "_article_cache") and canonical_id in self._article_cache:
                del self._article_cache[canonical_id]


    def record_feedback(self, query: str, answer: str, canonical_ids: List[str], rating: int, feedback_text: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_feedback (query, answer, canonical_ids, rating, feedback_text)
                VALUES (?, ?, ?, ?, ?)
            """, (query, answer, json.dumps(canonical_ids), rating, feedback_text))
            conn.commit()

    def get_feedback_records(self, limit: int = 50) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, query, answer, canonical_ids, rating, feedback_text, created_at
                FROM user_feedback
                ORDER BY id DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM articles_metadata")
            return cursor.fetchone()[0]
