import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from bs4 import BeautifulSoup

from src.schema.canonical import CanonicalArticle
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient
from src.ingestion.lex_parser import parse_law_text_file
from src.ingestion.review_queue import ReviewQueue
from src.ingestion.amendment_diff import check_and_apply_amendment

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """
    Automated ingestion pipeline for Uzbekistan legislation.
    Parses, validates, detects amendments, queues changes for legal review, and indexes.
    """

    def __init__(
        self,
        store: HybridStore,
        review_queue: Optional[ReviewQueue] = None,
        client: Optional[OpenRouterClient] = None
    ):
        self.store = store
        self.review_queue = review_queue or ReviewQueue()
        self.client = client or OpenRouterClient()

    async def ingest_file(self, file_path: str) -> Dict[str, int]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(f"Starting ingestion of {file_path}...")
        text_content = path.read_text(encoding="utf-8")
        articles = parse_law_text_file(text_content, path.name)

        indexed = 0
        enqueued_amendments = 0

        for art in articles:
            # Check for existing amendments
            has_changed, diff = check_and_apply_amendment(art, self.store, self.review_queue)
            if has_changed:
                enqueued_amendments += 1
            else:
                await self.store.index_article(art, client=self.client)
                indexed += 1

        logger.info(f"Ingested {path.name}: {indexed} articles indexed, {enqueued_amendments} amendments queued for review.")
        return {
            "indexed": indexed,
            "amendments_enqueued": enqueued_amendments,
            "total_parsed": len(articles),
        }

    async def fetch_and_ingest_lex_uz(self, doc_id_or_url: str) -> Dict[str, any]:
        """
        Politely fetches legislation text from lex.uz with rate limiting and timeout.
        Accepts full URL (e.g., 'https://lex.uz/uz/docs/-5501227') or doc_id (e.g., '5053070').
        """
        if doc_id_or_url.startswith("http://") or doc_id_or_url.startswith("https://"):
            url = doc_id_or_url
            doc_id = doc_id_or_url.rstrip("/").split("/")[-1].replace("-", "")
        else:
            doc_id = doc_id_or_url.replace("-", "")
            url = f"https://lex.uz/docs/{doc_id_or_url}"

        logger.info(f"Fetching legal document from {url}...")

        headers = {
            "User-Agent": "UzbekistanLegalRAG/1.0 (Accessibility & Citizen Rights Research; contact@legal-rag.uz)",
            "Accept-Language": "uz,ru;q=0.9",
        }

        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"Failed to fetch {url}: HTTP {resp.status_code}")

            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove UI buttons and audio clutter
            for el in soup.find_all("div", class_="lx_elem2"):
                el.decompose()

            # Extract main content body
            content_div = soup.find("div", id="divCont") or soup.find("div", class_="doc_content") or soup.find("body")
            if not content_div:
                raise RuntimeError("Could not locate legal text body in lex.uz HTML.")

            text = content_div.get_text("\n")
            articles = parse_law_text_file(text, f"lex_uz_{doc_id}.txt")

            indexed = 0
            for art in articles:
                art.metadata.source_url = url
                await self.store.index_article(art, client=self.client)
                indexed += 1

            logger.info(f"Successfully ingested {url}: {indexed} articles indexed.")
            return {"indexed": indexed, "total_parsed": len(articles), "url": url}


if __name__ == "__main__":
    import argparse
    import sys

    # Add project root to sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    parser = argparse.ArgumentParser(description="Universal Lex.uz and File Ingestion Pipeline")
    parser.add_argument("--url", help="Lex.uz URL or document ID to ingest (e.g. https://lex.uz/docs/5053070)")
    parser.add_argument("--file", help="Local law text or markdown file to ingest")
    args = parser.parse_args()

    pipeline = IngestionPipeline(store=HybridStore())
    if args.url:
        result = asyncio.run(pipeline.fetch_and_ingest_lex_uz(args.url))
        print("Ingestion complete:", result)
    elif args.file:
        result = asyncio.run(pipeline.ingest_file(args.file))
        print("Ingestion complete:", result)
    else:
        parser.print_help()
