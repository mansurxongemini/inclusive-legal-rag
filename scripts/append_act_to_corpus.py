#!/usr/bin/env python3
"""
scripts/append_act_to_corpus.py - Ingest a newly added act into built_articles.json and SQLite FTS store.
"""
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingestion.corpus_builder import CorpusBuilder, SourceSpec
from src.ingestion.lex_client import LexClient
from src.storage.hybrid_store import HybridStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("append_act")

def append_act(lex_id: str, store_dir: str = "data/store"):
    registry_path = Path("data/sources/disability_registry.json")
    built_path = Path("data/sources/built_articles.json")

    with open(registry_path, "r", encoding="utf-8") as f:
        reg = json.load(f)

    target_doc = None
    for d in reg.get("documents", []):
        lid = str(d.get("lex_id", "")).strip()
        if lid == lex_id or lid.lstrip("-") == lex_id.lstrip("-"):
            target_doc = d
            break

    if not target_doc:
        raise ValueError(f"Hujjat {lex_id} reestrda topilmadi!")

    spec = SourceSpec.from_dict({
        **target_doc,
        "number": target_doc.get("number_override", "") or target_doc.get("number", ""),
        "title_hint": target_doc.get("title", "")
    })

    client = LexClient(cache_dir="data/raw_lex")
    builder = CorpusBuilder(client)
    doc, ru_doc = builder.load(spec, with_russian=True)
    articles, report = builder.to_articles(doc, spec, ru_doc)

    log.info(f"Parsed {len(articles)} articles for {spec.number} ({lex_id}).")

    # 1. Update built_articles.json
    existing_articles = []
    if built_path.exists():
        with open(built_path, "r", encoding="utf-8") as f:
            existing_articles = json.load(f)

    existing_ids = {a.get("canonical_id") for a in existing_articles}
    new_count = 0
    updated_count = 0

    articles_dict = [a.model_dump() for a in articles]
    for a in articles_dict:
        cid = a.get("canonical_id")
        if cid in existing_ids:
            # Replace
            for idx, ex in enumerate(existing_articles):
                if ex.get("canonical_id") == cid:
                    existing_articles[idx] = a
                    updated_count += 1
                    break
        else:
            existing_articles.append(a)
            new_count += 1

    with open(built_path, "w", encoding="utf-8") as f:
        json.dump(existing_articles, f, ensure_ascii=False, indent=2)

    log.info(f"built_articles.json yangilandi: +{new_count} yangi, {updated_count} yangilangan. Jami: {len(existing_articles)}")

    # 2. Update SQLite Store
    store = HybridStore(store_dir)
    indexed_count = 0
    for art in articles:
        store.fts_store.upsert_article(art)
        indexed_count += 1

    with store.fts_store._get_connection() as conn:
        total = conn.cursor().execute("SELECT count(*) FROM articles_metadata").fetchone()[0]
    log.info(f"Jami bazadagi moddalar soni: {total}")

if __name__ == "__main__":
    import sys
    lex_id = sys.argv[1] if len(sys.argv) > 1 else "-7730821"
    append_act(lex_id)
