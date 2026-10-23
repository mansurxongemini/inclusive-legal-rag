"""Apply ADD decisions from data/sources/collection_plan.json to data/sources/disability_registry.json."""
from datetime import date
import json
import logging
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.ingestion.lex_client import LexClient
from src.ingestion.lex_structured import LexDocumentParser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("apply_plan")

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCES = BASE_DIR / "data" / "sources"
RAW = BASE_DIR / "data" / "raw"
PLAN_FILE = SOURCES / "collection_plan.json"
REG_FILE = SOURCES / "disability_registry.json"


def main():
    if not PLAN_FILE.exists():
        sys.exit(f"Plan file not found: {PLAN_FILE}")
    if not REG_FILE.exists():
        sys.exit(f"Registry file not found: {REG_FILE}")

    with open(PLAN_FILE, "r", encoding="utf-8") as f:
        plan = json.load(f)
    with open(REG_FILE, "r", encoding="utf-8") as f:
        registry = json.load(f)

    existing_docs = registry.get("documents", [])
    doc_map = {d["lex_id"]: d for d in existing_docs}

    add_items = [p for p in plan if p.get("decision") == "ADD"]
    log.info(f"Loaded {len(add_items)} ADD items from {PLAN_FILE}")

    lex_client = LexClient(cache_dir=str(RAW), min_delay=0.1)
    parser = LexDocumentParser()

    new_count = 0
    updated_count = 0
    unchanged_count = 0

    for idx, item in enumerate(add_items, 1):
        lex_id = item["lex_id"]
        target_include = item.get("include", "all")

        if lex_id in doc_map:
            cur = doc_map[lex_id]
            if cur.get("include") != target_include:
                old_inc = cur.get("include")
                cur["include"] = target_include
                cur["updated_at"] = date.today().isoformat()
                log.info(f"[{idx}/{len(add_items)}] UPDATE {lex_id} ({item.get('number')}): include {old_inc} -> {target_include}")
                updated_count += 1
            else:
                unchanged_count += 1
            continue

        # Brand new document: fetch, parse and register
        html = lex_client.fetch_document(lex_id)
        if not html:
            log.error(f"[{idx}/{len(add_items)}] FAILED to fetch HTML for {lex_id}")
            continue

        parsed = parser.parse(html, lex_id)
        if parsed.status != "active":
            log.warning(f"[{idx}/{len(add_items)}] Non-active status ({parsed.status}) for {lex_id}, registering anyway")

        entry = {
            "lex_id": lex_id,
            "law_id": "",
            "number": parsed.number or item.get("number") or "",
            "number_override": "",
            "title": parsed.title or item.get("title") or "",
            "doc_type": parsed.doc_type or item.get("doc_type") or "",
            "adopted": parsed.adopted_date or item.get("adopted") or "",
            "effective": parsed.effective_date or "",
            "tier": 2,
            "include": target_include,
            "category": None,
            "nodes": [],
            "relevance_title": 0,
            "relevance_text": 0,
            "units": len(parsed.units),
            "verified_at": date.today().isoformat(),
            "source": "collection_plan",
        }
        existing_docs.append(entry)
        doc_map[lex_id] = entry
        new_count += 1
        log.info(f"[{idx}/{len(add_items)}] ADD NEW {lex_id}: {entry['number']} - {entry['title'][:40]} | units={len(parsed.units)}, include={target_include}")

    lex_client.close()

    registry["documents"] = existing_docs
    registry["updated_at"] = date.today().isoformat()

    # Sort documents by tier, then lex_id
    existing_docs.sort(key=lambda d: (d.get("tier", 3), d.get("lex_id", 0)))

    with open(REG_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

    log.info("=" * 60)
    log.info(f"Successfully applied collection plan to {REG_FILE}:")
    log.info(f"  Brand new acts added: {new_count}")
    log.info(f"  Existing acts updated: {updated_count}")
    log.info(f"  Already matching: {unchanged_count}")
    log.info(f"  Total documents in registry now: {len(existing_docs)}")


if __name__ == "__main__":
    main()
