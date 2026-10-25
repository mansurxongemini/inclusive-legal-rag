#!/usr/bin/env python3
"""
Embeds the articles that are in the text index (SQLite FTS5) but have no vectors in LanceDB.

Vector-only: the text index is not touched. Safe to re-run: the missing set is recomputed on every start, so an
interrupted run resumes where it stopped.

    python scripts/embed_missing.py                 # dry run: counts, chunks, token and cost estimate
    python scripts/embed_missing.py --run           # backup, endpoint check, embed everything missing
    python scripts/embed_missing.py --run --limit 50  # small trial first
    python scripts/embed_missing.py --fill-chunk-index [--run]
                                                    # re-embed multi-chunk articles whose vectors have no chunk_index
    python scripts/embed_missing.py --extend-chunks [--run]
                                                    # re-embed units that have more chunks than the 14 the index held

Embeddings go through OPENROUTER_BASE_URL (https://openrouter.ai/api/v1) with OPENROUTER_API_KEY, like every other call.
"""
import argparse
import asyncio
import logging
import math
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.config import settings  # noqa: E402
from src.storage.chunking import LEGACY_CHUNK_CAP, build_chunks, chunk_layout  # noqa: E402
from src.storage.hybrid_store import HybridStore, vector_languages  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("embed_missing")

CHARS_PER_TOKEN = 3.0          # conservative for Uzbek/Russian text
USD_PER_MTOK = 0.01            # qwen3-embedding-8b (and bge-m3) on OpenRouter; check the current price, this is only an estimate


def lancedb_ids(store: HybridStore) -> set:
    table = store.vector_store.table
    if len(table) == 0:
        return set()
    arrow = table.search().select(["canonical_id"]).limit(len(table) + 10).to_arrow()
    return set(arrow.column("canonical_id").to_pylist())


def ids_without_chunk_index(store: HybridStore) -> set:
    """Articles with at least one vector row that predates chunk_index (all of them when the column is missing)."""
    table = store.vector_store.table
    if len(table) == 0:
        return set()
    if not store.vector_store.has_chunk_index:
        return lancedb_ids(store)
    arrow = table.search().where("chunk_index < 0").select(["canonical_id"]).limit(len(table) + 10).to_arrow()
    return set(arrow.column("canonical_id").to_pylist())


def multi_chunk_ids(store: HybridStore, ids: list) -> list:
    """Articles with more than one embedded chunk in a vector language: the only ones where chunk_index matters."""
    return [art.canonical_id for art in load(store, ids)
            if any(len(build_chunks(art, lang)) > 1 for lang in vector_languages(art))]


def long_unit_ids(store: HybridStore, ids: list) -> list:
    """Units whose uncapped layout has more chunks than the index used to hold, in a vector language."""
    out = []
    for art in load(store, ids):
        for lang in vector_languages(art):
            layout = chunk_layout(art, lang)
            if layout is not None and len(layout.texts) > LEGACY_CHUNK_CAP:
                out.append(art.canonical_id)
                break
    return out


def fts_ids(store: HybridStore) -> list:
    conn = store.fts_store._get_connection()
    try:
        return [r[0] for r in conn.execute("SELECT canonical_id FROM articles_metadata ORDER BY canonical_id")]
    finally:
        conn.close()


def load(store: HybridStore, ids: list):
    for i in range(0, len(ids), 200):
        found = store.get_articles_batch(ids[i:i + 200])
        for cid in ids[i:i + 200]:
            if cid in found:
                yield found[cid]


def estimate(store: HybridStore, ids: list) -> dict:
    chunks = chars = 0
    by_lang = Counter()
    no_text = 0
    for art in load(store, ids):
        n_art = 0
        for lang in vector_languages(art):
            texts = build_chunks(art, lang)
            n_art += len(texts)
            by_lang[lang] += len(texts)
            chunks += len(texts)
            chars += sum(len(t) for t in texts)
        no_text += n_art == 0
    tokens = int(chars / CHARS_PER_TOKEN)
    return {"chunks": chunks, "chars": chars, "tokens": tokens, "by_lang": dict(by_lang), "no_text": no_text,
            "usd": tokens / 1e6 * USD_PER_MTOK}


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def check_endpoint(store: HybridStore, client: OpenRouterClient, known_ids: set) -> None:
    """Refuses to write unless the endpoint is OpenRouter and returns vectors from the SAME space as the stored ones."""
    host = client.base_url.split("/")[2] if "//" in client.base_url else client.base_url
    if client.embedding_is_mock:
        sys.exit("Embedding is in mock mode (no OPENROUTER_API_KEY or MOCK_EXTERNAL_APIS=true). Nothing written.")
    if "openrouter.ai" not in host:
        sys.exit(f"The endpoint is {host}, not openrouter.ai. Set OPENROUTER_BASE_URL and OPENROUTER_API_KEY in .env. Nothing written.")

    # several articles that already have vectors: re-embed their first chunk and compare with the stored vectors.
    # Same model => own similarity is high (old chunk headers/text may differ a little) and clearly above other articles.
    table = store.vector_store.table
    probes = []
    for cid in sorted(known_ids)[:600:40]:
        art = store.get_article(cid)
        if art and build_chunks(art, "uz"):
            probes.append((cid, build_chunks(art, "uz")[0]))
        if len(probes) == 5:
            break
    if len(probes) < 3:
        sys.exit("Not enough stored articles to verify the embedding space. Nothing written.")
    new = await client.get_embeddings([t for _, t in probes])
    if any(len(v) != settings.EMBEDDING_DIMENSION or not any(v) for v in new):
        sys.exit(f"Bad embedding dimension (expected {settings.EMBEDDING_DIMENSION}). Nothing written.")
    stored = {cid: [list(r["vector"]) for r in table.search().where(f"canonical_id = '{cid}' AND language = 'uz'").limit(30).to_list()]
              for cid, _ in probes}
    own, gaps = [], []
    for (cid, _), vec in zip(probes, new):
        o = max((cosine(vec, s) for s in stored[cid]), default=0.0)
        other = max((cosine(vec, s) for oc, v in stored.items() if oc != cid for s in v), default=0.0)
        own.append(o)
        gaps.append(o - other)
    mean_own = sum(own) / len(own)
    logger.info(f"Endpoint {host}: dim={len(new[0])}, similarity to stored vectors: mean {mean_own:.3f}, min {min(own):.3f}, "
                f"min gap to other articles {min(gaps):.3f}")
    # the gap guards against an endpoint returning near-identical vectors; an exact reproduction (>= 0.99) needs none
    if mean_own < 0.93 or min(own) < 0.85 or (min(gaps) < 0.2 and min(own) < 0.99):
        sys.exit("This endpoint/model does not reproduce the stored vectors (different model or space). Nothing written.")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="really embed (default is a dry run)")
    ap.add_argument("--limit", type=int, default=0, help="embed at most N articles (trial run)")
    ap.add_argument("--group", type=int, default=300, help="articles per progress group")
    ap.add_argument("--batch-size", type=int, default=15)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--extend-chunks", action="store_true",
                    help="re-embed the units longer than the old 14-chunk cap, so that their later chunks are searchable")
    ap.add_argument("--fill-chunk-index", action="store_true",
                    help="re-embed multi-chunk articles whose vectors have no chunk_index (instead of missing ones)")
    args = ap.parse_args()

    store = HybridStore()
    known = lancedb_ids(store)
    all_ids = fts_ids(store)
    if args.extend_chunks:
        missing = long_unit_ids(store, all_ids)
        logger.info(f"Units with more than {LEGACY_CHUNK_CAP} chunks in uz or ru (to re-embed whole): {len(missing)}")
    elif args.fill_chunk_index:
        no_index = ids_without_chunk_index(store)
        missing = multi_chunk_ids(store, [c for c in all_ids if c in no_index])
        logger.info(f"Vector table has chunk_index: {store.vector_store.has_chunk_index} | articles with rows "
                    f"without it: {len(no_index)} | multi-chunk among them (to re-embed): {len(missing)}")
    else:
        missing = [c for c in all_ids if c not in known]
        stale = len(known - set(all_ids))
        logger.info(f"FTS articles: {len(all_ids)} | with vectors: {len(known)} | missing: {len(missing)} | vectors without text: {stale}")
    if not missing:
        logger.info("Nothing to do.")
        return

    todo = missing[:args.limit] if args.limit else missing
    est = estimate(store, todo)
    prefixes = Counter(c.split("_")[0] for c in todo).most_common(8)
    logger.info(f"To embed: {len(todo)} articles -> {est['chunks']} chunks {est['by_lang']}, {est['chars']:,} chars, "
                f"~{est['tokens']:,} tokens, est. ${est['usd']:.3f} (at ${USD_PER_MTOK}/M tokens), "
                f"{est['no_text']} without text in uz/ru")
    logger.info(f"By prefix: {prefixes}")
    if not args.run:
        logger.info("Dry run only. Add --run to embed.")
        return

    client = OpenRouterClient()
    await check_endpoint(store, client, known)

    if not args.no_backup:
        dest = Path("data/backups") / f"store_before_embed_missing_{time.strftime('%Y%m%d_%H%M%S')}"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(Path(settings.STORAGE_DIR) / "lancedb", dest / "lancedb")
        logger.info(f"LanceDB backup: {dest}")

    if args.fill_chunk_index and store.vector_store.ensure_chunk_index_column():
        logger.info("Added chunk_index column (-1 for existing rows)")

    done = failed = 0
    started = time.time()
    for i in range(0, len(todo), args.group):
        group_ids = todo[i:i + args.group]
        articles = list(load(store, group_ids))
        try:
            await store.reembed_articles(articles, client=client, batch_size=args.batch_size, concurrency=args.concurrency)
            done += len(articles)
        except Exception as e:
            failed += len(articles)
            logger.error(f"Group starting at {i} failed ({e}); it will be retried by the next run.")
        rate = (done + failed) / max(time.time() - started, 1)
        logger.info(f"Progress {done + failed}/{len(todo)} (ok {done}, failed {failed}) | {rate:.1f} articles/s")

    try:
        store.vector_store.optimize()
    except Exception as e:  # compaction is an optimisation only
        logger.warning(f"optimize failed: {e}")
    await client.close()

    after = lancedb_ids(store)
    if args.fill_chunk_index:
        still = multi_chunk_ids(store, [c for c in todo if c in ids_without_chunk_index(store)])
    else:
        still = [c for c in all_ids if c not in after]
    logger.info(f"Done. Articles with vectors: {len(after)} | still to do: {len(still)}")
    if still:
        logger.info(f"Run again to retry the rest, e.g. {still[:3]}")


if __name__ == "__main__":
    asyncio.run(main())
