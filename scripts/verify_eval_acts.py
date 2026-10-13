#!/usr/bin/env python3
"""
Verify acts in the practical evaluation dataset against official Lex.uz pages.

Reads dataset (e.g. data/golden_dataset/practical_eval_set.json) and verifies:
1. Every expected_lex_id can be fetched via LexClient and parsed via LexDocumentParser.
2. The act status is NOT repealed (active acts only).
3. The parsed document number matches one of the expected_law_numbers (apostrophe-agnostic).
4. The title is present and non-empty.
5. in_corpus flag accurately reflects presence in data/sources/disability_registry.json.

Outputs a formatted table and exits with code 1 if any discrepancy is found.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingestion.lex_client import LexClient  # noqa: E402
from src.ingestion.lex_structured import LexDocumentParser  # noqa: E402


def normalize_act_number(s: Optional[str]) -> str:
    """Normalizes an act number: apostrophes -> ', uppercase, stripped spaces."""
    if not s:
        return ""
    val = re.sub(r"[’‘`ʻʼ\u02bb\u02bc]", "'", str(s))
    val = re.sub(r"\s+", " ", val).strip().upper()
    return re.sub(r"\s*-\s*", "-", val)


def verify_dataset(
    dataset_path: str,
    cache_dir: str = "data/raw_lex",
    registry_path: str = "data/sources/disability_registry.json",
    min_delay: float = 1.0,
) -> int:
    path = Path(dataset_path)
    if not path.exists():
        print(f"Error: Dataset not found: {dataset_path}")
        return 1

    items = json.loads(path.read_text(encoding="utf-8"))
    print(f"Loaded {len(items)} items from {dataset_path}")

    # Load registry
    reg_file = Path(registry_path)
    registry_lex_ids = set()
    if reg_file.exists():
        reg_data = json.loads(reg_file.read_text(encoding="utf-8"))
        registry_lex_ids = {d["lex_id"] for d in reg_data.get("documents", [])}
        print(f"Loaded {len(registry_lex_ids)} act IDs from registry: {registry_path}")
    else:
        print(f"Warning: Registry file not found: {registry_path}")

    client = LexClient(cache_dir=cache_dir, min_delay=min_delay)
    parser = LexDocumentParser()

    errors = []
    rows = []

    print("\nVerifying each expected act against Lex.uz...")
    for idx, item in enumerate(items, start=1):
        item_id = item.get("id", f"item_{idx}")
        lex_ids = item.get("expected_lex_ids", [])
        expected_numbers = item.get("expected_law_numbers", [])
        in_corpus = bool(item.get("in_corpus"))

        if not lex_ids:
            errors.append(f"{item_id}: No expected_lex_ids provided")
            continue

        item_has_corpus = any(lid in registry_lex_ids for lid in lex_ids)
        if in_corpus != item_has_corpus:
            errors.append(
                f"{item_id}: in_corpus={in_corpus} does not match registry presence ({item_has_corpus}) "
                f"for lex_ids={lex_ids}"
            )

        norm_exp_numbers = {normalize_act_number(n) for n in expected_numbers if n is not None}

        for lid in lex_ids:
            try:
                html = client.fetch_document(lid)
                if not html:
                    errors.append(f"{item_id} ({lid}): Failed to fetch document HTML (empty)")
                    continue
                doc = parser.parse(html, doc_id=lid)
            except Exception as e:
                errors.append(f"{item_id} ({lid}): Fetch/parse error: {e}")
                continue

            # Check status
            if doc.status == "repealed":
                errors.append(f"{item_id} ({lid}): Document is repealed! (repealed_date={doc.repealed_date})")

            # Check title
            if not doc.title:
                errors.append(f"{item_id} ({lid}): Document title is empty!")

            # Check number match
            norm_doc_no = normalize_act_number(doc.number)
            is_number_match = norm_doc_no in norm_exp_numbers
            if not is_number_match:
                errors.append(
                    f"{item_id} ({lid}): Parsed number {doc.number!r} (norm: {norm_doc_no!r}) "
                    f"not in expected_law_numbers {expected_numbers} (norm: {norm_exp_numbers})"
                )

            rows.append({
                "id": item_id,
                "lex_id": lid,
                "status": doc.status,
                "parser_no": doc.number or "(none)",
                "expected_no": ", ".join(str(n) for n in expected_numbers) or "(none)",
                "in_corpus": "YES" if (lid in registry_lex_ids) else "NO",
                "match": "OK" if (is_number_match and doc.status != "repealed" and doc.title) else "FAIL",
                "title": doc.title[:45] + ("..." if len(doc.title) > 45 else ""),
            })

    # Print Table
    header = f"{'ID':<6} | {'Lex ID':<10} | {'Status':<8} | {'Parser No':<15} | {'Expected No':<18} | {'Corpus':<6} | {'Match':<5} | {'Title'}"
    print("\n" + "=" * len(header))
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['id']:<6} | {r['lex_id']:<10} | {r['status']:<8} | {r['parser_no']:<15} | "
            f"{r['expected_no']:<18} | {r['in_corpus']:<6} | {r['match']:<5} | {r['title']}"
        )
    print("=" * len(header))

    if errors:
        print(f"\nFAILURE: {len(errors)} error(s) found:")
        for err in errors:
            print(f"  [X] {err}")
        return 1
    else:
        print(f"\nSUCCESS: All {len(rows)} verified acts matched official Lex.uz records (0 errors).")
        return 0


def main():
    ap = argparse.ArgumentParser(description="Verify eval acts against official Lex.uz portal")
    ap.add_argument("--dataset", default=str(ROOT / "data" / "golden_dataset" / "practical_eval_set.json"))
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "raw_lex"))
    ap.add_argument("--registry", default=str(ROOT / "data" / "sources" / "disability_registry.json"))
    ap.add_argument("--min-delay", type=float, default=1.0)
    args = ap.parse_args()

    sys.exit(verify_dataset(args.dataset, cache_dir=args.cache_dir, registry_path=args.registry, min_delay=args.min_delay))


if __name__ == "__main__":
    main()
