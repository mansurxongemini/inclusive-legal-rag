#!/usr/bin/env python3
"""
Ingestion script for the Constitution of the Republic of Uzbekistan (2023 New Revision).
Official Lex.uz Document: https://lex.uz/docs/6445145 (Uzbek) & https://lex.uz/docs/6445147 (Russian).
Supreme Law of the Republic of Uzbekistan with direct effect (To'g'ridan-to'g'ri amal qiluvchi asosiy qonun).
"""

import asyncio
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
import httpx
from bs4 import BeautifulSoup

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.schema.canonical import (
    CanonicalArticle,
    ArticleMetadata,
    ArticlePoint,
    ArticleStatus,
    TranslationProvenanceType,
)
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient
from scripts.ingest_all_laws import parse_law_articles, parse_russian_clauses

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def fetch_and_ingest_constitution():
    uz_url = "https://lex.uz/docs/6445145"
    ru_url = "https://lex.uz/docs/6445147"

    headers = {
        "User-Agent": "UzbekistanLegalRAG/1.0 (Government & Citizen Legal Access Research; contact@legal-rag.uz)",
        "Accept-Language": "uz,ru;q=0.9",
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as http_client:
        logger.info(f"Fetching Uzbek Constitution from {uz_url}...")
        resp_uz = await http_client.get(uz_url)
        if resp_uz.status_code != 200:
            logger.error(f"Failed to fetch Uzbek Constitution: HTTP {resp_uz.status_code}")
            return

        logger.info(f"Fetching Russian Constitution from {ru_url}...")
        resp_ru = await http_client.get(ru_url)
        ru_clauses = {}
        if resp_ru.status_code == 200:
            ru_clauses = parse_russian_clauses(resp_ru.text)
            logger.info(f"Parsed {len(ru_clauses)} Russian Constitution articles.")

    articles: List[CanonicalArticle] = parse_law_articles(
        html_text=resp_uz.text,
        slug="constitution_uz",
        law_number="Konstitutsiya-2023",
        law_title="O'zbekiston Respublikasi Konstitutsiyasi",
        effective_date="2023-05-01",
        source_url=uz_url,
    )

    logger.info(f"Parsed {len(articles)} Uzbek Constitution articles.")

    # Pair with Russian text and set metadata
    for art in articles:
        art.metadata.category = "constitution"
        art.metadata.law_title = {
            "uz": "O'zbekiston Respublikasi Konstitutsiyasi",
            "ru": "Конституция Республики Узбекистан",
            "en": "Constitution of the Republic of Uzbekistan",
        }
        art.metadata.beneficiary_type = ["citizen", "individual", "state_body", "legal_entity"]

        m_num = re.search(r"(\d+)", art.metadata.article_number)
        if m_num and m_num.group(1) in ru_clauses:
            ru_title, ru_body = ru_clauses[m_num.group(1)]
            art.translations["ru"] = ru_body if ru_body else ru_title
            art.metadata.article_title["ru"] = ru_title if ru_title else f"Статья {m_num.group(1)}"
            art.translation_provenance["ru"] = TranslationProvenanceType.OFFICIAL

    # Save to catalog cache
    output_dir = Path("data/laws_catalog")
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_file = output_dir / "constitution_uz.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump([a.model_dump() for a in articles], f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(articles)} articles to {cache_file}")

    # Index into database
    store = HybridStore()
    client = OpenRouterClient()
    logger.info(f"Indexing Constitution articles into LanceDB and SQLite FTS5...")
    indexed = await store.index_articles_batch(articles, client=client, batch_size=25)
    logger.info(f"Successfully indexed {indexed} Constitution articles! Store count: {store.count()}")


if __name__ == "__main__":
    asyncio.run(fetch_and_ingest_constitution())
