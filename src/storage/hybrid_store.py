import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from src.schema.canonical import CanonicalArticle
from src.storage.vector_store import LanceVectorStore
from src.storage.fts_store import SqliteFtsStore
from src.clients.openrouter import OpenRouterClient
from src.config import settings

logger = logging.getLogger(__name__)


class HybridStore:
    """Unified storage interface combining embedded LanceDB vectors and SQLite FTS5 BM25."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir or settings.STORAGE_DIR)
        self.vector_store = LanceVectorStore(str(self.storage_dir))
        self.fts_store = SqliteFtsStore(str(self.storage_dir / "legal_rag.db"))

    async def index_article(self, article: CanonicalArticle, client: Optional[OpenRouterClient] = None):
        """Indexes an article across FTS and LanceDB vector stores."""
        # 1. Save metadata and full-text search
        self.fts_store.upsert_article(article)

        # 2. Compute vectors for each translation
        if client is None:
            client = OpenRouterClient()

        vector_records = []
        texts_to_embed = []
        langs = []
        for lang, text in article.translations.items():
            if not text.strip():
                continue
            law_title = article.get_law_title(lang) or article.metadata.law_number
            doc_text = f"{law_title} | {article.metadata.article_number} {article.get_title(lang)}. {text}"
            texts_to_embed.append(doc_text)
            langs.append(lang)

        if texts_to_embed:
            embeddings = await client.get_embeddings(texts_to_embed)
            for lang, vector in zip(langs, embeddings):
                vector_records.append({
                    "canonical_id": article.canonical_id,
                    "vector": vector,
                    "language": lang,
                    "status": article.metadata.status.value,
                    "category": article.metadata.category,
                    "disability_types": json.dumps(article.metadata.disability_types),
                    "embedding_model_version": article.metadata.embedding_model_version,
                })

        # 3. Save to LanceDB
        if vector_records:
            self.vector_store.upsert_vectors(vector_records)

    async def index_articles_batch(
        self,
        articles: List[CanonicalArticle],
        client: Optional[OpenRouterClient] = None,
        batch_size: int = 15,
    ) -> int:
        """High-throughput batch indexing for large codes and bulk legislation."""
        if not articles:
            return 0

        if client is None:
            client = OpenRouterClient()

        # 1. Batch upsert FTS/SQLite metadata
        for art in articles:
            self.fts_store.upsert_article(art)

        # 2. Batch embeddings (both UZ and RU when available)
        total_indexed = 0
        for i in range(0, len(articles), batch_size):
            chunk = articles[i : i + batch_size]
            texts_to_embed = []
            mapping = []

            for art in chunk:
                for lang in ["uz", "ru"]:
                    text = art.translations.get(lang, "")
                    if text and text.strip():
                        law_title = art.get_law_title(lang) or art.metadata.law_number
                        doc_text = f"{law_title} | {art.metadata.article_number} {art.get_title(lang)}. {text[:1400]}"
                        texts_to_embed.append(doc_text)
                        mapping.append((
                            art.canonical_id,
                            lang,
                            art.metadata.status.value,
                            art.metadata.category,
                            json.dumps(art.metadata.disability_types),
                            art.metadata.embedding_model_version,
                        ))

            if texts_to_embed:
                embeddings = await client.get_embeddings(texts_to_embed)
                vector_records = []
                for (cid, lang, status, cat, dt, emv), vec in zip(mapping, embeddings):
                    vector_records.append({
                        "canonical_id": cid,
                        "vector": vec,
                        "language": lang,
                        "status": status,
                        "category": cat,
                        "disability_types": dt,
                        "embedding_model_version": emv,
                    })
                self.vector_store.upsert_vectors(vector_records)
                total_indexed += len(chunk)

        return total_indexed

    def get_article(self, canonical_id: str) -> Optional[CanonicalArticle]:
        return self.fts_store.get_article(canonical_id)

    def get_articles_batch(self, canonical_ids: List[str]) -> Dict[str, CanonicalArticle]:
        return self.fts_store.get_articles_batch(canonical_ids)


    def list_articles(self, limit: int = 100, offset: int = 0) -> List[CanonicalArticle]:
        return self.fts_store.list_articles(limit, offset)

    def delete_article(self, canonical_id: str):
        self.fts_store.delete_article(canonical_id)
        self.vector_store.delete_by_canonical_id(canonical_id)

    def count(self) -> int:
        return self.fts_store.count()

    async def seed_from_file(self, file_path: str, client: Optional[OpenRouterClient] = None):
        """Seeds articles from a JSON file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data:
            article = CanonicalArticle.model_validate(item)
            await self.index_article(article, client=client)
        logger.info(f"Seeded {len(data)} articles from {file_path}")
