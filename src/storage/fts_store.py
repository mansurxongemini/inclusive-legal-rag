import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from src.config import settings
from src.schema.canonical import CanonicalArticle
from src.storage.sqlite_utils import connect as _sqlite_connect
from src.nlp.transliteration import normalize_apostrophes

logger = logging.getLogger(__name__)

_INNER_APOSTROPHE = re.compile(r"(?<=\w)'(?=\w)")


def fts_text(text: str) -> str:
    """
    Text as it is stored in / matched against the FTS5 index.

    The unicode61 tokenizer splits "bo'lgan" at the apostrophe into "bo" + "lgan", while the query builder
    glues the letters ("bolgan"), so every word with o' / g' / ' (a large share of Uzbek) could never match.
    Both sides now use the apostrophe-free form: bo'lgan -> bolgan, to'siqsiz -> tosiqsiz, ta'lim -> talim.
    """
    return _INNER_APOSTROPHE.sub("", normalize_apostrophes(text or ""))


def build_fts_terms(query: str) -> List[str]:
    """
    FTS5 prefix terms of a question: `"word"*`, whole words. Each word is quoted, and quotes and other characters that FTS5
    treats as syntax are stripped, so a question can never inject an operator. Numbers and codes (483-modda, VMQ-62) stay whole.
    Dropping question words and cutting words to a search stem were measured on the stress set and made the ranking worse
    (hit@1 68-70% against 72.7%): the whole-word list is what the ranking was tuned on.
    """
    words = []
    for word in fts_text(query).replace('"', '').replace("'", "").split():
        clean = "".join(c for c in word if c.isalnum() or c in "-_")
        if clean:
            words.append(clean)
    terms: List[str] = []
    for w in words:
        term = f'"{w}"*'
        if term not in terms:
            terms.append(term)
    return terms


def fts_rows(article: CanonicalArticle) -> List[tuple]:
    """
    Rows of the FTS index for one unit: one per language holding the whole text and, for a unit longer than
    FTS_CHUNK_MIN_CHARS, one more row per chunk. BM25 normalises by document length, so a paragraph about day-care
    tax exemption inside a 51 000-character Tax Code article was invisible next to short units; as its own row it
    competes on equal terms. The search returns each unit once (bm25_search).
    """
    from src.storage.chunking import chunk_layout       # chunking imports the schema only; kept lazy for import order

    rows = []
    number, law_number = fts_text(article.metadata.article_number), fts_text(article.metadata.law_number)
    for lang, body in article.translations.items():
        if not body or not body.strip():
            continue
        title = fts_text(article.get_title(lang))
        rows.append((article.canonical_id, lang, number, law_number, title, fts_text(article.to_fts_document(lang))))
        if settings.FTS_CHUNK_MIN_CHARS and len(body) > settings.FTS_CHUNK_MIN_CHARS:
            layout = chunk_layout(article, lang)
            for chunk in (layout.texts if layout else []):
                rows.append((article.canonical_id, lang, number, law_number, title, fts_text(chunk)))
    return rows


def _unique(rows, limit: int) -> list:
    """First `limit` rows with distinct canonical_id, order kept."""
    seen, out = set(), []
    for r in rows:
        if r["canonical_id"] not in seen:
            seen.add(r["canonical_id"])
            out.append(r)
            if len(out) >= limit:
                break
    return out


class SqliteFtsStore:
    """Embedded SQLite FTS5 store for BM25 full-text search and canonical article storage."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or (Path(settings.STORAGE_DIR) / "legal_rag.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = _sqlite_connect(self.db_path, timeout=60.0)
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
        self._invalidate_derived()
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

            cursor.executemany("""
                INSERT INTO articles_fts (
                    canonical_id, language, article_number, law_number, title, body
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, fts_rows(article))

            conn.commit()
            if hasattr(self, "_article_cache"):
                self._article_cache[article.canonical_id] = article

    def bm25_search(
        self,
        query: str,
        language: str = "uz",
        top_k: int = 20,
    ) -> List[Dict]:
        """
        Executes BM25 search on FTS5 virtual table.
        Returns list of {canonical_id, score, rank}.
        """
        if language in [l.strip() for l in settings.FTS_EXCLUDE_LANGUAGES.split(",") if l.strip()]:
            return []
        clean_terms = build_fts_terms(query)
        if not clean_terms:
            return []

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
                """, (and_query, language, top_k * 4))
                rows = _unique(cursor.fetchall(), top_k)

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
                    """, (or_query, language, top_k * 6))
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
                    """, (or_query, top_k * 4))
                    rows = _unique(cursor.fetchall(), top_k)

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

    def _invalidate_derived(self) -> None:
        """Indexes derived from the stored texts (src/retrieval/repeal_notices.py) are rebuilt after any write."""
        from src.retrieval.repeal_notices import invalidate
        invalidate(self)

    def clear_article_cache(self) -> None:
        """Drops the in-memory article objects and the indexes derived from the texts."""
        if hasattr(self, "_article_cache"):
            self._article_cache.clear()
        self._invalidate_derived()

    def files_stamp(self) -> str:
        """Changes whenever a commit reaches the database, from this process or another (modification times of the
        database file and its write-ahead log)."""
        return ":".join(str(os.stat(p).st_mtime_ns) if os.path.exists(p) else "0"
                        for p in (self.db_path, f"{self.db_path}-wal"))

    def _drop_cache_after_external_write(self) -> None:
        """Another process (a refresh run of the corpus build script) writes behind this one's back: a repealed or
        amended act would keep being served from the cache. The database and its write-ahead log change their
        modification time on every commit, from any process; when they did since the last read, the cache goes."""
        stamp = self.files_stamp()
        if stamp != getattr(self, "_files_stamp", None):
            if getattr(self, "_files_stamp", None) is not None:
                self.clear_article_cache()
            self._files_stamp = stamp

    def get_article(self, canonical_id: str) -> Optional[CanonicalArticle]:
        if not hasattr(self, "_article_cache"):
            self._article_cache = {}
        self._drop_cache_after_external_write()
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
        self._drop_cache_after_external_write()

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


    def iter_link_metadata(self):
        """
        Yields {canonical_id, law_id, source_type, source_url, ru_document_id, source_element_id, source_element_ids,
        ru_element_ids} of every unit WITHOUT loading its texts (json_extract in SQLite). Building the Huquq+ link index from
        list_articles() parsed all 28 000 units with their full texts and left the server 600 MB heavier for good.
        """
        fields = ("law_id", "source_type", "source_url", "ru_document_id", "source_element_id", "source_element_ids", "ru_element_ids")
        select = ", ".join(f"json_extract(json_data, '$.metadata.{f}')" for f in fields)
        conn = self._get_connection()
        try:
            for row in conn.execute(f"SELECT canonical_id, {select} FROM articles_metadata"):
                rec = {"canonical_id": row[0]}
                for name, value in zip(fields, row[1:]):
                    if name in ("source_element_ids", "ru_element_ids") and isinstance(value, str):
                        try:
                            value = json.loads(value)
                        except json.JSONDecodeError:
                            value = []
                    rec[name] = value
                yield rec
        finally:
            conn.close()

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
        self._invalidate_derived()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM articles_metadata WHERE canonical_id = ?", (canonical_id,))
            cursor.execute("DELETE FROM articles_fts WHERE canonical_id = ?", (canonical_id,))
            conn.commit()
            if hasattr(self, "_article_cache") and canonical_id in self._article_cache:
                del self._article_cache[canonical_id]


    def rebuild_fts_index(self) -> int:
        """Recreates every FTS row from the stored canonical JSON (after a tokenization change; no embeddings)."""
        n = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM articles_fts")
            rows = cursor.execute("SELECT json_data FROM articles_metadata").fetchall()
            for row in rows:
                art = CanonicalArticle.model_validate_json(row["json_data"])
                cursor.executemany(
                    "INSERT INTO articles_fts (canonical_id, language, article_number, law_number, title, body) "
                    "VALUES (?, ?, ?, ?, ?, ?)", fts_rows(art))
                n += 1
            conn.commit()
        return n

    def clear_articles(self) -> int:
        """Removes every article (metadata + full-text index). Feedback and other tables are untouched."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM articles_metadata")
            n = cursor.fetchone()[0]
            cursor.execute("DELETE FROM articles_metadata")
            cursor.execute("DELETE FROM articles_fts")
            conn.commit()
        if hasattr(self, "_article_cache"):
            self._article_cache.clear()
        self._invalidate_derived()
        return n

    def delete_laws(self, law_ids: List[str]) -> List[str]:
        """Deletes every article of the given laws; returns the removed canonical ids."""
        self._invalidate_derived()
        if not law_ids:
            return []
        removed: List[str] = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for i in range(0, len(law_ids), 200):
                chunk = law_ids[i:i + 200]
                ph = ",".join("?" for _ in chunk)
                cursor.execute(
                    f"SELECT canonical_id FROM articles_metadata WHERE json_extract(json_data, '$.metadata.law_id') IN ({ph})",
                    chunk,
                )
                ids = [r[0] for r in cursor.fetchall()]
                for j in range(0, len(ids), 500):
                    sub = ids[j:j + 500]
                    sph = ",".join("?" for _ in sub)
                    cursor.execute(f"DELETE FROM articles_metadata WHERE canonical_id IN ({sph})", sub)
                    cursor.execute(f"DELETE FROM articles_fts WHERE canonical_id IN ({sph})", sub)
                removed.extend(ids)
            conn.commit()
        if hasattr(self, "_article_cache"):
            for cid in removed:
                self._article_cache.pop(cid, None)
        return removed

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

    def list_documents(
        self,
        search_query: Optional[str] = None,
        doc_type: Optional[str] = None,
        authority: Optional[str] = None,
    ) -> List[Dict]:
        """
        Aggregates articles_metadata into distinct legal documents.
        Returns document list with authority, doc_type, norm counts, and metadata.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COALESCE(json_extract(json_data, '$.metadata.law_number'), 'Nomaʼlum') as law_num,
                    COALESCE(json_extract(json_data, '$.metadata.law_title.uz'), json_extract(json_data, '$.metadata.law_title.ru'), 'Nomaʼlum') as law_title,
                    json_extract(json_data, '$.metadata.law_id') as law_id,
                    json_extract(json_data, '$.metadata.category') as category,
                    json_extract(json_data, '$.metadata.source_url') as source_url,
                    COUNT(*) as norm_count
                FROM articles_metadata
                WHERE (json_extract(json_data, '$.metadata.source_type') = 'lex' OR json_extract(json_data, '$.metadata.source_type') IS NULL)
                  AND canonical_id NOT LIKE 'hp_%' AND canonical_id NOT LIKE 'qa_%'
                GROUP BY json_extract(json_data, '$.metadata.law_id')
                ORDER BY norm_count DESC
            """)
            rows = cursor.fetchall()
            docs = []
            q_clean = (search_query or "").strip().lower()
            # Acts with at least one unit containing the query, found in ONE pass. Asking per act (518 full scans with
            # json_extract) took 90 s for "641" and made the public search endpoint a denial-of-service lever.
            matching_law_ids: set = set()
            if q_clean:
                escaped = q_clean.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                # the unit's text and title only: the raw JSON also holds URLs and element ids ("#-5641...") that
                # matched almost any number
                # SQLite's LIKE folds the case of ASCII letters only: "факсимильная" must also find "Факсимильная"
                conn.create_function("ulower", 1, lambda v: v.lower() if isinstance(v, str) else v, deterministic=True)
                cursor.execute("""
                    SELECT DISTINCT json_extract(json_data, '$.metadata.law_id') FROM articles_metadata
                    WHERE ulower(json_extract(json_data, '$.translations.uz')) LIKE ?1 ESCAPE '\\'
                       OR ulower(json_extract(json_data, '$.metadata.article_title.uz')) LIKE ?1 ESCAPE '\\'
                       OR ulower(json_extract(json_data, '$.translations.ru')) LIKE ?1 ESCAPE '\\'
                       OR ulower(json_extract(json_data, '$.metadata.article_title.ru')) LIKE ?1 ESCAPE '\\'
                """, (f"%{escaped}%",))
                matching_law_ids = {row[0] for row in cursor.fetchall()}

            for r in rows:
                law_num = r["law_num"]
                law_title = r["law_title"]
                law_id = r["law_id"] or law_num
                category = r["category"] or "general"
                source_url = r["source_url"] or "https://lex.uz"
                norm_count = r["norm_count"]

                detected_auth, detected_type = detect_authority_and_type(law_num, law_title)

                if doc_type and doc_type != "all" and detected_type.lower() != doc_type.lower():
                    continue

                if authority and authority != "all" and authority.lower() not in detected_auth.lower():
                    continue

                if q_clean:
                    haystack = f"{law_num} {law_title} {detected_auth} {detected_type} {category}".lower()
                    if q_clean not in haystack and r["law_id"] not in matching_law_ids:
                        continue

                docs.append({
                    "law_number": law_num,
                    "law_title": law_title,
                    "law_id": law_id,
                    "category": category,
                    "source_url": source_url,
                    "norm_count": norm_count,
                    "authority": detected_auth,
                    "doc_type": detected_type,
                })
            if q_clean:
                # acts whose number or title holds the query first ("641" -> O'RQ-641), then those with a matching norm
                docs.sort(key=lambda d: 0 if q_clean in d["law_number"].lower() else 1 if q_clean in d["law_title"].lower() else 2)
            return docs

    def get_articles_by_law(self, law_identifier: str) -> List[Dict]:
        """
        Retrieves all statutory articles/norms belonging to a specific law.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT canonical_id, json_data, status, category, last_verified_date
                FROM articles_metadata
                WHERE json_extract(json_data, '$.metadata.law_number') = ?
                   OR json_extract(json_data, '$.metadata.law_id') = ?
                ORDER BY canonical_id ASC
            """, (law_identifier, law_identifier))
            rows = cursor.fetchall()
            articles = []
            for r in rows:
                try:
                    data = json.loads(r["json_data"])
                    meta = data.get("metadata", {})
                    translations = data.get("translations", {})
                    title_obj = meta.get("article_title", {})
                    title = title_obj.get("uz") or title_obj.get("ru") or meta.get("article_number", "")
                    
                    articles.append({
                        "canonical_id": r["canonical_id"],
                        "article_number": meta.get("article_number", ""),
                        "title": title,
                        "law_number": meta.get("law_number", ""),
                        "law_title": (meta.get("law_title", {}) or {}).get("uz") or meta.get("law_number", ""),
                        "category": meta.get("category", r["category"]),
                        "disability_types": meta.get("disability_types", []),
                        "source_url": meta.get("source_url", "https://lex.uz"),
                        "status": r["status"],
                        "text_uz": translations.get("uz", ""),
                        "text_ru": translations.get("ru", ""),
                        "preview": (translations.get("uz") or "")[:250] + ("..." if len(translations.get("uz", "")) > 250 else ""),
                        "last_verified_date": r["last_verified_date"],
                    })
                except Exception as e:
                    logger.warning(f"Error parsing article {r['canonical_id']}: {e}")
                    continue
            return articles


def detect_authority_and_type(law_number: Optional[str], law_title: Optional[str]) -> tuple[str, str]:
    num = (law_number or "").upper()
    title = (law_title or "").lower()

    # Authority detection
    if "BMT" in num or "konvensiya" in title or "bmt" in title:
        authority = "BMT (Xalqaro shartnoma)"
        doc_type = "Boshqa"
    elif "O‘RQ" in num or "O'RQ" in num or "ORQ" in num or "-XII" in num or "oliy majlis" in title:
        authority = "Oliy Majlis"
        doc_type = "Qonun"
    elif "PF" in num or "farmon" in title:
        authority = "O‘zbekiston Respublikasi Prezidenti"
        doc_type = "Farmon"
    elif "PQ" in num or "prezident qarori" in title or "prezidentining qarori" in title:
        authority = "O‘zbekiston Respublikasi Prezidenti"
        doc_type = "Qaror"
    elif "VMQ" in num or "vazirlar mahkamasi" in title:
        authority = "Vazirlar Mahkamasi"
        doc_type = "Qaror"
    elif "IHMA" in num or "ijtimoiy himoya" in title or "agentligi" in title:
        authority = "Ijtimoiy himoya milliy agentligi"
        doc_type = "Buyruq"
    elif "SSV" in num or "sog‘liqni saqlash" in title or "sog'liqni saqlash" in title or "vazirligi" in title:
        authority = "Sog‘liqni saqlash vazirligi"
        doc_type = "Buyruq"
    else:
        if "kodeks" in title or "qonun" in title:
            authority = "Oliy Majlis"
            doc_type = "Qonun"
        elif "qaror" in title:
            authority = "Vazirlar Mahkamasi"
            doc_type = "Qaror"
        elif "buyruq" in title:
            authority = "Vazirlik va idoralar"
            doc_type = "Buyruq"
        else:
            authority = "Boshqa davlat organi"
            doc_type = "Boshqa"

    if doc_type == "Boshqa":
        if "kodeks" in title or "qonun" in title:
            doc_type = "Qonun"
        elif "qaror" in title:
            doc_type = "Qaror"
        elif "farmon" in title:
            doc_type = "Farmon"
        elif "buyruq" in title:
            doc_type = "Buyruq"

    return authority, doc_type

