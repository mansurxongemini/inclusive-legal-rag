#!/usr/bin/env python3
"""
Autonomous Legal Ingestion CLI Entrypoint.
Executes the universal legal pipeline in foreground or daemon mode.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion.universal_engine import (
    CORE_REGULATIONS_REGISTRY,
    DocumentSpec,
    UniversalAutonomousEngine,
)
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/store/ingestion_engine.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)


def show_status(engine: UniversalAutonomousEngine):
    store = engine.store
    total_articles = store.count()
    completed = engine.state.completed_slugs
    failed = engine.state.failed_slugs

    print("\n" + "=" * 65)
    print("📊 UZBEKISTAN LEGAL RAG — AUTONOMOUS INGESTION STATUS")
    print("=" * 65)
    print(f"🏛️  Total articles indexed: {total_articles:,}")
    print(f"📋  Completed document specs: {len(completed)}")
    print(f"❌  Failed document specs: {len(failed)}")
    print(f"⏱️  Last state update: {engine.state.last_updated or 'Never'}")
    print("-" * 65)

    if completed:
        print("Completed Acts:")
        for slug, info in completed.items():
            print(f"  • {slug:<24} | {info.get('count', 0):>4} articles | {info.get('title', '')[:40]}")

    if failed:
        print("\nFailed Acts:")
        for slug, err in failed.items():
            print(f"  • {slug:<24} | Error: {err}")

    print("=" * 65 + "\n")


async def run_daemon(engine: UniversalAutonomousEngine, interval_hours: int = 24):
    logger.info(f"🚀 Starting Autonomous Ingestion Daemon (Poll interval: {interval_hours}h)...")
    while True:
        try:
            logger.info("Running scheduled ingestion cycle...")
            res = await engine.run_pipeline(CORE_REGULATIONS_REGISTRY, force_reindex=False)
            logger.info(f"Ingestion cycle completed: {res}")
        except Exception as e:
            logger.error(f"Error in daemon cycle: {e}", exc_info=True)

        logger.info(f"Sleeping for {interval_hours} hours...")
        await asyncio.sleep(interval_hours * 3600)


async def main():
    parser = argparse.ArgumentParser(description="Autonomous Legal RAG Ingestion Pipeline")
    parser.add_argument("--status", action="store_true", help="Display current ingestion status and exit")
    parser.add_argument("--regulations", action="store_true", help="Ingest all registered core Government Regulations")
    parser.add_argument("--all", action="store_true", help="Run full pipeline across all categories")
    parser.add_argument("--doc", type=str, help="Ingest a specific Lex.uz URL or Doc ID")
    parser.add_argument("--slug", type=str, help="Slug for the specific doc", default=None)
    parser.add_argument("--title", type=str, help="Title for the specific doc", default="Normativ hujjat")
    parser.add_argument("--force", action="store_true", help="Force re-indexing of already completed documents")
    parser.add_argument("--daemon", action="store_true", help="Run in continuous background daemon mode")

    args = parser.parse_args()

    store = HybridStore()
    client = OpenRouterClient()
    engine = UniversalAutonomousEngine(store=store, client=client)

    if args.status:
        show_status(engine)
        return

    if args.doc:
        url = args.doc if args.doc.startswith("http") else f"https://lex.uz/docs/{args.doc}"
        doc_id = url.rstrip("/").split("/")[-1].replace("-", "")
        slug = args.slug or f"vmq_doc_{doc_id}"
        spec = DocumentSpec(
            slug=slug,
            category="regulations",
            doc_number=f"Hujjat #{doc_id}",
            title_uz=args.title,
            effective_date="2022-01-01",
            url_uz=url,
            parser_type="regulation_clause",
            max_point_number=350,
        )
        logger.info(f"Processing specific document {slug}...")
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as hc:
            await engine.ingest_spec(spec, hc, force_reindex=args.force)
        show_status(engine)
        return

    if args.daemon:
        await run_daemon(engine)
        return

    if args.regulations or args.all or len(sys.argv) == 1:
        logger.info("Executing Autonomous Ingestion of Core Government Regulations...")
        result = await engine.run_pipeline(CORE_REGULATIONS_REGISTRY, force_reindex=args.force)
        logger.info(f"Pipeline Result: {result}")
        show_status(engine)


if __name__ == "__main__":
    asyncio.run(main())
