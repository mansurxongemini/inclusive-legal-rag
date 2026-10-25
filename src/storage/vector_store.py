"""
Vector store of the article embeddings: one SQLite file (vectors.db), exact cosine search with numpy.

The corpus is about 39 000 vectors of 1024 numbers (160 MB). A matrix product over all of them takes about 20 ms, so no
approximate index is needed and the answer is exact. SQLite holds the rows (transactional writes, the online backup of
scripts/backup_store.py covers it like every other database of the store); the matrix is read from it on the first search
and again after any write, from this process or another. Plain wheels of numpy run on every x86-64 CPU; the vector
database this replaced (LanceDB) crashed with "Illegal instruction" on CPUs without AVX2 (Xeon E5-2670 of the target server).
"""
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

import numpy as np

from src.config import settings
from src.storage.sqlite_utils import connect

logger = logging.getLogger(__name__)

DB_NAME = "vectors.db"

# Nearest chunk rows read per wanted unit (several chunks can belong to one unit). 8 measured no better: hit@1 -2.9 on the stress set,
# within noise.
VECTOR_WINDOW_FACTOR = 4

_COLUMNS = "canonical_id, language, status, category, disability_types, embedding_model_version, chunk_index, vector"


@dataclass(frozen=True)
class _Snapshot:
    """The matrix of unit-length vectors and what the search needs to know about each row. Never modified after it is built."""
    stamp: str
    matrix: np.ndarray                 # (rows, dimension) float32, every row of length 1
    canonical_ids: List[str]
    statuses: List[str]
    chunk_indexes: List[int]
    language_codes: np.ndarray         # per row: index into `languages`
    languages: List[str]


class VectorStore:
    """Embeddings of the legal units (EMBEDDING_MODEL, EMBEDDING_DIMENSION numbers each), one row per chunk."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir or settings.STORAGE_DIR)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / DB_NAME
        # Indexing runs in worker threads (the event loop must stay free while a law is imported). An upsert is a delete
        # followed by inserts, so two of them must never interleave.
        self._write_lock = threading.RLock()
        self._load_lock = threading.Lock()
        self._snapshot: Optional[_Snapshot] = None
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS articles_vectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_id TEXT NOT NULL,
                    language TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    disability_types TEXT NOT NULL DEFAULT '',
                    embedding_model_version TEXT NOT NULL DEFAULT '',
                    chunk_index INTEGER NOT NULL DEFAULT -1,     -- position in chunking.build_chunks(article, language); -1 unknown
                    vector BLOB NOT NULL                          -- little-endian float32, EMBEDDING_DIMENSION numbers
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_vectors_cid ON articles_vectors(canonical_id)")

    def _connect(self):
        return connect(self.db_path, timeout=60)

    # -- writing ------------------------------------------------------------------------------------------------

    def upsert_vectors(self, records: List[Dict]) -> None:
        """
        Replaces the vectors of the records' units. Each record has: canonical_id, vector, language, status, category,
        disability_types, embedding_model_version and optionally chunk_index.
        """
        if not records:
            return

        # Only VECTOR_LANGUAGES are stored: a record of another language is a caller's mistake, not a row to keep
        allowed = settings.vector_language_list
        foreign = {r.get("language") for r in records} - set(allowed)
        if foreign:
            logger.warning(f"Skipping vector records of languages outside VECTOR_LANGUAGES: {sorted(map(str, foreign))}")
            records = [r for r in records if r.get("language") in allowed]
            if not records:
                return

        dimension = settings.EMBEDDING_DIMENSION
        rows = []
        for r in records:
            vector = np.asarray(r["vector"], dtype="<f4")
            if vector.shape != (dimension,):
                raise ValueError(f"The vector of {r['canonical_id']} has {vector.size} numbers, expected {dimension}")
            chunk_index = r.get("chunk_index")
            rows.append((r["canonical_id"], r["language"], str(r.get("status") or ""), str(r.get("category") or ""),
                         str(r.get("disability_types") or ""), str(r.get("embedding_model_version") or ""),
                         -1 if chunk_index is None else int(chunk_index), vector.tobytes()))

        with self._write_lock, self._connect() as conn:
            conn.executemany("DELETE FROM articles_vectors WHERE canonical_id = ?",
                             [(cid,) for cid in {row[0] for row in rows}])
            conn.executemany(f"INSERT INTO articles_vectors ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        self._snapshot = None

    def delete_by_canonical_id(self, canonical_id: str) -> None:
        self.delete_many([canonical_id])

    def delete_many(self, canonical_ids: List[str]) -> None:
        if not canonical_ids:
            return
        with self._write_lock, self._connect() as conn:
            conn.executemany("DELETE FROM articles_vectors WHERE canonical_id = ?", [(c,) for c in canonical_ids])
        self._snapshot = None

    def reset(self) -> None:
        """Removes every embedding."""
        with self._write_lock, self._connect() as conn:
            conn.execute("DELETE FROM articles_vectors")
        self._snapshot = None

    def set_model_version(self, model: str) -> int:
        """Labels every row as made by `model` (after a full re-embedding). Returns the number of rows."""
        with self._write_lock, self._connect() as conn:
            return conn.execute("UPDATE articles_vectors SET embedding_model_version = ?", (model,)).rowcount

    def compact(self) -> dict:
        """Returns the space freed by deletes to the file system (after a full re-embedding). Never raises."""
        try:
            before = self.size_bytes()
            with self._write_lock, self._connect() as conn:
                conn.isolation_level = None
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("VACUUM")
            return {"bytes_before": before, "bytes_after": self.size_bytes()}
        except Exception as e:
            logger.warning(f"Could not compact {self.db_path.name}: {e}")
            return {}

    # -- reading ------------------------------------------------------------------------------------------------

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT count(*) FROM articles_vectors").fetchone()[0]

    def size_bytes(self) -> int:
        return sum(os.path.getsize(p) for p in (self.db_path, f"{self.db_path}-wal") if os.path.exists(p))

    def canonical_ids(self) -> Set[str]:
        """Units that have at least one vector."""
        with self._connect() as conn:
            return {r[0] for r in conn.execute("SELECT DISTINCT canonical_id FROM articles_vectors")}

    def ids_without_chunk_index(self) -> Set[str]:
        """Units with a row whose chunk position is unknown (-1): embedded before chunk_index was recorded."""
        with self._connect() as conn:
            return {r[0] for r in conn.execute("SELECT DISTINCT canonical_id FROM articles_vectors WHERE chunk_index < 0")}

    def vectors_of(self, canonical_id: str, language: Optional[str] = None) -> List[np.ndarray]:
        """The stored vectors (one per chunk) of a unit, as stored (not normalised)."""
        sql, args = "SELECT vector FROM articles_vectors WHERE canonical_id = ?", [canonical_id]
        if language:
            sql, args = sql + " AND language = ?", args + [language]
        with self._connect() as conn:
            return [np.frombuffer(r[0], dtype="<f4") for r in conn.execute(sql, args)]

    def models(self) -> Dict[str, int]:
        """Rows per embedding model label."""
        with self._connect() as conn:
            return dict(conn.execute("SELECT embedding_model_version, count(*) FROM articles_vectors "
                                     "GROUP BY embedding_model_version").fetchall())

    def _stamp(self) -> str:
        """Changes whenever a commit reaches the database, from this process or another."""
        parts = []
        for p in (self.db_path, f"{self.db_path}-wal"):
            st = os.stat(p) if os.path.exists(p) else None
            parts.append(f"{st.st_mtime_ns}:{st.st_size}" if st else "0")
        return "|".join(parts)

    def _matrix(self) -> _Snapshot:
        snap = self._snapshot
        stamp = self._stamp()
        if snap is not None and snap.stamp == stamp:
            return snap
        with self._load_lock:
            snap = self._snapshot
            stamp = self._stamp()
            if snap is None or snap.stamp != stamp:
                snap = self._snapshot = self._read(stamp)
            return snap

    def _read(self, stamp: str) -> _Snapshot:
        with self._connect() as conn:
            conn.execute("BEGIN")                 # one consistent view for the count and the rows
            total = conn.execute("SELECT count(*) FROM articles_vectors").fetchone()[0]
            cursor = conn.execute("SELECT canonical_id, language, status, chunk_index, vector FROM articles_vectors ORDER BY id")
            matrix = np.empty((total, settings.EMBEDDING_DIMENSION), dtype=np.float32)
            ids: List[str] = []
            statuses: List[str] = []
            chunks: List[int] = []
            languages: List[str] = []
            codes = np.empty(total, dtype=np.int16)
            i = 0
            while True:
                batch = cursor.fetchmany(2000)
                if not batch:
                    break
                for cid, language, status, chunk_index, blob in batch:
                    matrix[i] = np.frombuffer(blob, dtype="<f4")
                    ids.append(cid)
                    statuses.append(status)
                    chunks.append(chunk_index)
                    if language not in languages:
                        languages.append(language)
                    codes[i] = languages.index(language)
                    i += 1
        norms = np.sqrt(np.einsum("ij,ij->i", matrix, matrix))
        norms[norms == 0] = 1.0
        matrix /= norms[:, None]
        return _Snapshot(stamp, matrix, ids, statuses, chunks, codes, languages)

    def search_vector(
        self,
        query_vector: List[float],
        top_k: int = 20,
        language: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> List[Dict]:
        """Nearest units by cosine similarity, best first: one entry per unit (its best-matching chunk)."""
        snap = self._matrix()
        query = np.asarray(query_vector, dtype=np.float32)
        norm = float(np.linalg.norm(query))
        if snap.matrix.shape[0] == 0 or norm == 0.0:
            return []
        if query.shape != (snap.matrix.shape[1],):
            raise ValueError(f"The query vector has {query.size} numbers, the store holds {snap.matrix.shape[1]}")

        similarity = snap.matrix @ (query / norm)
        # rows of other languages (e.g. restored from an old backup) are never searched
        wanted = [snap.languages.index(l) for l in settings.vector_language_list if l in snap.languages]
        searchable = np.isin(snap.language_codes, wanted)
        candidates = int(searchable.sum())
        if candidates == 0:
            return []
        similarity = np.where(searchable, similarity, -2.0)

        # Several chunk rows can belong to one unit (long units are embedded chunk by chunk), so the window is wide
        # enough for top_k distinct units even when one long unit fills many of the nearest rows.
        window = min(top_k * VECTOR_WINDOW_FACTOR, candidates)
        nearest = np.argpartition(similarity, -window)[-window:]
        nearest = nearest[np.argsort(-similarity[nearest], kind="stable")]

        best: Dict[str, Dict] = {}
        for row in nearest:
            status = snap.statuses[row]
            if status_filter and status != status_filter:
                continue
            cid = snap.canonical_ids[row]
            score = (1.0 + float(similarity[row])) / 2.0        # cosine distance d = 1 - cos; score = 1 - d / 2

            # Modest bonus for exact language match
            row_language = snap.languages[snap.language_codes[row]]
            if language and row_language == language:
                score += 0.03

            if cid not in best or score > best[cid]["score"]:
                chunk_index = snap.chunk_indexes[row]
                best[cid] = {
                    "canonical_id": cid,
                    "score": score,
                    "language": row_language,
                    "status": status,
                    # the best-matching chunk of the article (None when the row predates chunk_index)
                    "chunk_index": chunk_index if chunk_index >= 0 else None,
                }

        return sorted(best.values(), key=lambda x: x["score"], reverse=True)[:top_k]
