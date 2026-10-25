#!/usr/bin/env python3
"""
Re-embed legal units whose vector chunks carry chapter or annex context, or (--all) every unit of the store: the way to
change the embedding model (EMBEDDING_MODEL / EMBEDDING_REQUEST_DIMENSIONS). With --all the store's model marker
(embedding_model.json, see src/storage/hybrid_store.py) is rewritten only after every unit has new vectors; until then
the service keeps full-text search only. The run is resumable (progress file) - stop the server first.

Usage:
  python scripts/reembed_context.py --dry-run
  python scripts/reembed_context.py --store-dir data/store --batch-size 15 --concurrency 3
  EMBEDDING_MODEL=qwen/qwen3-embedding-8b EMBEDDING_REQUEST_DIMENSIONS=1024 \
      python scripts/reembed_context.py --all --batch-size 40 --concurrency 6
"""
import argparse
import asyncio
from datetime import timedelta
import json
import logging
from pathlib import Path
import sys
import time
from typing import List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.config import settings  # noqa: E402
from src.schema.canonical import CanonicalArticle  # noqa: E402
from src.storage.chunking import build_chunks, has_context_header  # noqa: E402
from src.storage.hybrid_store import HybridStore, vector_languages  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("reembed_context")


def load_progress(path: Path) -> List[str]:
    """Loads already completed canonical IDs from progress JSON file."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [str(cid) for cid in data]
    except Exception as e:
        logger.warning(f"Failed to read progress file {path}: {e}")
    return []


def save_progress(path: Path, done_ids: List[str]) -> None:
    """Atomically writes completed canonical IDs to progress JSON file."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(done_ids, f, indent=2)
    tmp.replace(path)


def collect_units_to_reembed(
    store: HybridStore,
    done_ids: Set[str],
    limit: Optional[int] = None,
    chunk_size: int = 500,
    every_unit: bool = False,
) -> List[CanonicalArticle]:
    """Iterates the FTS store to select units matching has_context_header (every unit with every_unit)."""
    offset = 0
    selected: List[CanonicalArticle] = []
    while True:
        articles = store.list_articles(limit=chunk_size, offset=offset)
        if not articles:
            break
        for art in articles:
            if (every_unit or has_context_header(art)) and art.canonical_id not in done_ids:
                selected.append(art)
                if limit is not None and len(selected) >= limit:
                    return selected
        offset += len(articles)
    return selected


def count_chunk_stats(articles: List[CanonicalArticle]) -> Tuple[int, int, int, int]:
    """Computes total units, chunks, characters, and estimated tokens across the vector languages."""
    total_units = len(articles)
    total_chunks = 0
    total_chars = 0
    for art in articles:
        for lang in vector_languages(art):
            chunks = build_chunks(art, lang)
            total_chunks += len(chunks)
            total_chars += sum(len(c) for c in chunks)
    estimated_tokens = round(total_chars / 4)
    return total_units, total_chunks, total_chars, estimated_tokens


def parse_args(args_list: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-embed legal units whose vector chunks carry chapter or annex context."
    )
    parser.add_argument(
        "--store-dir",
        default=settings.STORAGE_DIR,
        help="Storage directory containing legal_rag.db and lancedb",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print count of units, chunks, chars, and estimated tokens without embedding",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of units to re-embed",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=15,
        help="Batch size for embedding and LanceDB writes",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Maximum concurrent embedding requests",
    )
    parser.add_argument(
        "--no-optimize",
        action="store_true",
        help="Skip LanceDB table optimization at the end",
    )
    parser.add_argument(
        "--cleanup-days",
        type=int,
        default=7,
        help="Days of old versions to retain during optimization (0 = prune all)",
    )
    parser.add_argument(
        "--allow-mock",
        action="store_true",
        help="Allow running with mock embeddings (offline mode)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Re-embed every unit with the configured model and record it as the store's model (a model change)",
    )
    parser.add_argument(
        "--reset-progress",
        action="store_true",
        help="Reset progress file and re-embed all matching units",
    )
    return parser.parse_args(args_list)


async def main(args_list: Optional[List[str]] = None) -> int:
    args = parse_args(args_list)
    store = HybridStore(args.store_dir)
    progress_file = Path(args.store_dir) / "reembed_context.progress.json"

    if args.reset_progress and progress_file.exists():
        progress_file.unlink()
        logger.info(f"Reset progress file: {progress_file}")

    progress_list = load_progress(progress_file)
    done_ids = set(progress_list)
    if done_ids:
        logger.info(f"Loaded {len(done_ids)} previously re-embedded units from {progress_file}")

    units_to_reembed = collect_units_to_reembed(
        store, done_ids=done_ids, limit=args.limit, every_unit=args.all
    )

    units_count, total_chunks, total_chars, est_tokens = count_chunk_stats(units_to_reembed)

    if args.dry_run:
        print("Dry run summary:")
        print(f"  Units to re-embed: {units_count}")
        print(f"  Total chunks:      {total_chunks}")
        print(f"  Total characters:  {total_chars}")
        print(f"  Estimated tokens:  {est_tokens} (chars / 4)")
        return 0

    if not units_to_reembed:
        print("No units need re-embedding.")
        if progress_file.exists():
            progress_file.unlink()
        if not args.no_optimize:
            cleanup = (
                timedelta(days=args.cleanup_days)
                if args.cleanup_days > 0
                else timedelta(seconds=0)
            )
            store.vector_store.optimize(cleanup_older_than=cleanup)
        return 0

    client = OpenRouterClient()
    if client.is_mock and not args.allow_mock:
        sys.exit("OPENROUTER_API_KEY is not configured (mock mode). Pass --allow-mock to index with fake vectors.")

    async def on_batch(batch_cids: List[str]) -> None:
        progress_list.extend(batch_cids)
        save_progress(progress_file, progress_list)

    t0 = time.perf_counter()
    try:
        reembedded = await store.reembed_articles(
            units_to_reembed,
            client=client,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            on_batch=on_batch,
            new_model=args.all,
        )
    finally:
        await client.close()

    if args.all:
        if args.limit is not None or len(set(progress_list)) < store.count():
            print(f"Re-embedded {len(set(progress_list))} of {store.count()} units: the model marker is left as it was.")
            return 1
        # every vector row now comes from the configured model: label the rows and the store
        store.vector_store.table.update(values={"embedding_model_version": settings.EMBEDDING_MODEL})
        store.write_embedding_marker()
        print(f"Store model recorded: {store.stored_embedding()}")

    if progress_file.exists():
        progress_file.unlink()

    frag_before = None
    frag_after = None
    if not args.no_optimize:
        cleanup = (
            timedelta(days=args.cleanup_days)
            if args.cleanup_days > 0
            else timedelta(seconds=0)
        )
        opt_stats = store.vector_store.optimize(cleanup_older_than=cleanup)
        frag_before = opt_stats.get("fragments_before")
        frag_after = opt_stats.get("fragments_after")

    elapsed = time.perf_counter() - t0

    print("\nRe-embed summary:")
    print(f"  Units re-embedded: {reembedded}")
    print(f"  Chunks:            {total_chunks}")
    if frag_before is not None and frag_after is not None:
        print(f"  Fragments:         {frag_before} -> {frag_after}")
    print(f"  Elapsed:           {elapsed:.2f}s")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
