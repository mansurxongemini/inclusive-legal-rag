import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from src.schema.canonical import CanonicalArticle
from src.storage.vector_store import LanceVectorStore
from src.storage.fts_store import SqliteFtsStore
from src.storage.chunking import build_chunks
from src.clients.openrouter import OpenRouterClient
from src.config import settings

logger = logging.getLogger(__name__)


class HybridStore:
    """Unified storage interface combining embedded LanceDB vectors and SQLite FTS5 BM25."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir or settings.STORAGE_DIR)
        self.vector_store = LanceVectorStore(str(self.storage_dir))
        self.fts_store = SqliteFtsStore(str(self.storage_dir / "legal_rag.db"))
        self._default_client: Optional[OpenRouterClient] = None

    def _resolve_client(self, client: Optional[OpenRouterClient]) -> OpenRouterClient:
        """Returns the given client or one shared per-store fallback (not a new HTTP pool per call)."""
        if client is not None:
            return client
        if self._default_client is None:
            self._default_client = OpenRouterClient()
        return self._default_client

    async def index_article(self, article: CanonicalArticle, client: Optional[OpenRouterClient] = None):
        """Indexes an article across FTS and LanceDB vector stores.

        Embeddings are computed before anything is written, so a failing embedding service cannot leave the
        full-text index updated while the vectors still describe the previous text.
        """
        # 1. Compute vectors for every chunk of every language
        client = self._resolve_client(client)

        vector_records = []
        texts_to_embed: List[str] = []
        langs: List[str] = []
        for lang in article.translations:
            for chunk in build_chunks(article, lang):
                texts_to_embed.append(chunk)
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

        # 2. Persist metadata + full-text search, then vectors
        self.fts_store.upsert_article(article)
        if vector_records:
            self.vector_store.upsert_vectors(vector_records)

    def _prepare_article_chunks(
        self, articles: List[CanonicalArticle]
    ) -> Tuple[List[str], List[tuple]]:
        """Prepares text chunks and metadata mapping for embedding articles in uz and ru."""
        texts_to_embed: List[str] = []
        mapping: List[tuple] = []
        for art in articles:
            for lang in ("uz", "ru"):
                for text in build_chunks(art, lang):
                    texts_to_embed.append(text)
                    mapping.append((
                        art.canonical_id,
                        lang,
                        art.metadata.status.value,
                        art.metadata.category,
                        json.dumps(art.metadata.disability_types),
                        art.metadata.embedding_model_version,
                    ))
        return texts_to_embed, mapping

    def _build_vector_records(
        self, mapping: List[tuple], embeddings: List[List[float]]
    ) -> List[Dict]:
        """Aligns embedding vectors with metadata mapping into vector store records."""
        records: List[Dict] = []
        for (cid, lang, status, cat, dt, emv), vec in zip(mapping, embeddings):
            records.append({
                "canonical_id": cid,
                "vector": vec,
                "language": lang,
                "status": status,
                "category": cat,
                "disability_types": dt,
                "embedding_model_version": emv,
            })
        return records

    async def index_articles_batch(
        self,
        articles: List[CanonicalArticle],
        client: Optional[OpenRouterClient] = None,
        batch_size: int = 15,
    ) -> int:
        """High-throughput batch indexing for large codes and bulk legislation.

        Each chunk is embedded first and only then written (FTS + vectors), so a failing embedding service
        never leaves the text index ahead of the vectors.
        """
        if not articles:
            return 0

        client = self._resolve_client(client)

        total_indexed = 0
        for i in range(0, len(articles), batch_size):
            chunk = articles[i : i + batch_size]
            texts_to_embed, mapping = self._prepare_article_chunks(chunk)

            vector_records = []
            if texts_to_embed:
                embeddings = await client.get_embeddings(texts_to_embed)
                vector_records = self._build_vector_records(mapping, embeddings)

            for art in chunk:
                self.fts_store.upsert_article(art)
            if vector_records:
                self.vector_store.upsert_vectors(vector_records)
            total_indexed += len(chunk)

        if total_indexed > 0:
            try:
                self.vector_store.optimize()
            except Exception as e:
                logger.warning(f"Error optimizing vector store after batch indexing: {e}")

        return total_indexed

    async def reembed_articles(
        self,
        articles: List[CanonicalArticle],
        client: Optional[OpenRouterClient] = None,
        batch_size: int = 15,
        concurrency: int = 3,
        on_batch: Optional[Any] = None,
    ) -> int:
        """Vector-only re-indexing of already stored articles for languages 'uz' and 'ru'.

        Does NOT touch the FTS index. Embedding requests run concurrently bounded by
        concurrency; writes to LanceDB are serialized with an asyncio.Lock.
        Per batch: embeds first, then upsert_vectors, so a failing embedding call leaves
        that batch's old vectors intact.
        Awaits on_batch(done_cids) after each written batch.
        """
        if not articles:
            return 0

        client = self._resolve_client(client)
        batches = [articles[i : i + batch_size] for i in range(0, len(articles), batch_size)]

        sem = asyncio.Semaphore(concurrency)
        write_lock = asyncio.Lock()

        async def _process_batch(batch: List[CanonicalArticle]) -> None:
            texts_to_embed, mapping = self._prepare_article_chunks(batch)
            batch_cids = [art.canonical_id for art in batch]

            vector_records = []
            if texts_to_embed:
                async with sem:
                    embeddings = await client.get_embeddings(texts_to_embed)
                vector_records = self._build_vector_records(mapping, embeddings)

            async with write_lock:
                if vector_records:
                    self.vector_store.upsert_vectors(vector_records)
                if on_batch is not None:
                    res = on_batch(batch_cids)
                    if asyncio.iscoroutine(res):
                        await res

        await asyncio.gather(*[_process_batch(b) for b in batches])
        return len(articles)

    def get_article(self, canonical_id: str) -> Optional[CanonicalArticle]:
        return self.fts_store.get_article(canonical_id)

    def get_articles_batch(self, canonical_ids: List[str]) -> Dict[str, CanonicalArticle]:
        return self.fts_store.get_articles_batch(canonical_ids)


    def list_articles(self, limit: int = 100, offset: int = 0) -> List[CanonicalArticle]:
        return self.fts_store.list_articles(limit, offset)

    def delete_article(self, canonical_id: str):
        self.fts_store.delete_article(canonical_id)
        self.vector_store.delete_by_canonical_id(canonical_id)

    def clear_all_articles(self) -> int:
        """Empties the legal corpus (text index and vectors) - used before a full rebuild."""
        n = self.fts_store.clear_articles()
        self.vector_store.reset()
        return n

    def delete_laws(self, law_ids: List[str]) -> int:
        """Removes all articles (text + vectors) of the given laws, e.g. before re-importing them."""
        removed = self.fts_store.delete_laws(list(law_ids))
        self.vector_store.delete_many(removed)
        return len(removed)

    def count(self) -> int:
        return self.fts_store.count()

    def list_documents(
        self,
        search_query: Optional[str] = None,
        doc_type: Optional[str] = None,
        authority: Optional[str] = None,
    ) -> List[Dict]:
        return self.fts_store.list_documents(
            search_query=search_query,
            doc_type=doc_type,
            authority=authority,
        )

    def get_articles_by_law(self, law_identifier: str) -> List[Dict]:
        return self.fts_store.get_articles_by_law(law_identifier)


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
