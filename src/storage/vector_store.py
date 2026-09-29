import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
import lancedb
import pyarrow as pa
from src.config import settings

logger = logging.getLogger(__name__)


class LanceVectorStore:
    """Embedded LanceDB vector store for BGE-M3 1024-dim article embeddings."""

    TABLE_NAME = "articles_vectors"

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir or settings.STORAGE_DIR) / "lancedb"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.storage_dir))
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
        ])

        try:
            return self.db.open_table(self.TABLE_NAME)
        except Exception:
            return self.db.create_table(self.TABLE_NAME, schema=schema)

    def upsert_vectors(self, records: List[Dict]):
        """
        Upsert vector records.
        Each record has: canonical_id, vector, language, status, category, disability_types, embedding_model_version.
        """
        if not records:
            return

        # Delete existing entries with matching canonical_ids to avoid duplicates
        canonical_ids = list({r["canonical_id"] for r in records})
        if canonical_ids:
            try:
                # If table has records, delete old ones
                if len(self.table) > 0:
                    for cid in canonical_ids:
                        self.table.delete(f"canonical_id = '{cid}'")
            except Exception as e:
                logger.warning(f"Error during existing record deletion in LanceDB: {e}")

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
                seen_cids[cid] = {
                    "canonical_id": cid,
                    "score": float(score),
                    "language": r.get("language"),
                    "status": r.get("status"),
                    "category": r.get("category"),
                }

        # Sort descending by score
        sorted_results = sorted(seen_cids.values(), key=lambda x: x["score"], reverse=True)
        return sorted_results[:top_k]

    def delete_by_canonical_id(self, canonical_id: str):
        if len(self.table) > 0:
            self.table.delete(f"canonical_id = '{canonical_id}'")

    def count(self) -> int:
        return len(self.table)
