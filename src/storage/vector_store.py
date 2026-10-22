import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional
import lancedb
import pyarrow as pa
from src.config import settings

logger = logging.getLogger(__name__)


def _sql_quote(value: str) -> str:
    """Quotes a string literal for a LanceDB (DataFusion) filter expression."""
    return "'" + str(value).replace("'", "''") + "'"


class LanceVectorStore:
    """Embedded LanceDB vector store for BGE-M3 1024-dim article embeddings."""

    TABLE_NAME = "articles_vectors"

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir or settings.STORAGE_DIR) / "lancedb"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # interval=0 makes every read check for the newest table version. Without it a long-lived handle never
        # sees vectors written by another HybridStore instance (importers, ingestion scripts) until restart.
        self.db = lancedb.connect(str(self.storage_dir), read_consistency_interval=timedelta(seconds=0))
        self.table = self._get_or_create_table()

    def _get_or_create_table(self):
        schema = pa.schema([
            pa.field("canonical_id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), settings.EMBEDDING_DIMENSION)),
            pa.field("language", pa.string()),
            pa.field("status", pa.string()),
            pa.field("category", pa.string()),
            pa.field("disability_types", pa.string()),
            pa.field("embedding_model_version", pa.string()),
            pa.field("chunk_index", pa.int32()),          # position in chunking.build_chunks(article, language)
        ])

        try:
            return self.db.open_table(self.TABLE_NAME)
        except Exception:
            return self.db.create_table(self.TABLE_NAME, schema=schema)

    @property
    def has_chunk_index(self) -> bool:
        return "chunk_index" in self.table.schema.names

    def ensure_chunk_index_column(self) -> bool:
        """Adds chunk_index (-1 = unknown) to a table created before it existed. Returns True when it was added.

        Existing rows keep -1 until their article is embedded again (scripts/embed_missing.py --fill-chunk-index).
        """
        if self.has_chunk_index:
            return False
        self.table.add_columns({"chunk_index": "CAST(-1 AS INT)"})
        return True

    def upsert_vectors(self, records: List[Dict]):
        """
        Upsert vector records.
        Each record has: canonical_id, vector, language, status, category, disability_types, embedding_model_version.
        """
        if not records:
            return

        # Delete existing entries with matching canonical_ids to avoid duplicates in a single batch
        canonical_ids = list({r["canonical_id"] for r in records})
        if canonical_ids:
            try:
                if len(self.table) > 0:
                    cids_str = ", ".join(_sql_quote(cid) for cid in canonical_ids)
                    self.table.delete(f"canonical_id IN ({cids_str})")
            except Exception as e:
                logger.warning(f"Error during existing record deletion in LanceDB: {e}")

        # A table created before chunk_index existed rejects the extra field
        if not self.has_chunk_index and any("chunk_index" in r for r in records):
            records = [{k: v for k, v in r.items() if k != "chunk_index"} for r in records]

        # Add new records
        self.table.add(records)

    def search_vector(
        self,
        query_vector: List[float],
        top_k: int = 20,
        language: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> List[Dict]:
        """
        Performs vector similarity search. Returns records sorted by distance.
        """
        if len(self.table) == 0:
            return []

        search_query = self.table.search(query_vector).metric("cosine").limit(top_k * 4)

        results = search_query.to_list()
        
        # Deduplicate by canonical_id, boosting same language if available
        seen_cids = {}
        for r in results:
            if status_filter and r.get("status") != status_filter:
                continue
            cid = r["canonical_id"]
            dist = r.get("_distance", 1.0)
            score = max(0.0, 1.0 - (dist / 2.0))
            
            # Modest bonus for exact language match
            if language and r.get("language") == language:
                score += 0.03

            if cid not in seen_cids or score > seen_cids[cid]["score"]:
                chunk_index = r.get("chunk_index")
                seen_cids[cid] = {
                    "canonical_id": cid,
                    "score": float(score),
                    "language": r.get("language"),
                    "status": r.get("status"),
                    "category": r.get("category"),
                    # the best-matching chunk of the article (None when the row predates chunk_index)
                    "chunk_index": chunk_index if chunk_index is not None and chunk_index >= 0 else None,
                }

        # Sort descending by score
        sorted_results = sorted(seen_cids.values(), key=lambda x: x["score"], reverse=True)
        return sorted_results[:top_k]

    def delete_by_canonical_id(self, canonical_id: str):
        if len(self.table) > 0:
            self.table.delete(f"canonical_id = {_sql_quote(canonical_id)}")

    def reset(self) -> None:
        """Drops and recreates the vector table (all embeddings)."""
        try:
            self.db.drop_table(self.TABLE_NAME)
        except Exception:
            pass
        self.table = self._get_or_create_table()

    def delete_many(self, canonical_ids: List[str]) -> None:
        if not canonical_ids or len(self.table) == 0:
            return
        for i in range(0, len(canonical_ids), 200):
            chunk = canonical_ids[i:i + 200]
            self.table.delete(f"canonical_id IN ({', '.join(_sql_quote(c) for c in chunk)})")

    def count(self) -> int:
        return len(self.table)

    def optimize(self, cleanup_older_than: Optional[timedelta] = None) -> dict:
        """Compact fragments and prune old versions in the vector table.

        Default keeps versions younger than 7 days; timedelta(seconds=0) prunes all.
        Returns {'fragments_before': int, 'fragments_after': int} via table.stats().
        Never raises: logs a warning and returns {} on error.
        """
        if cleanup_older_than is None:
            cleanup_older_than = timedelta(days=7)
        try:
            stats_before = self.table.stats()
            frag_before = stats_before.get("fragment_stats", {}).get("num_fragments", 0)
            self.table.optimize(cleanup_older_than=cleanup_older_than)
            stats_after = self.table.stats()
            frag_after = stats_after.get("fragment_stats", {}).get("num_fragments", 0)
            return {
                "fragments_before": frag_before,
                "fragments_after": frag_after,
            }
        except Exception as e:
            logger.warning(f"Error optimizing LanceDB table {self.TABLE_NAME}: {e}")
            return {}
