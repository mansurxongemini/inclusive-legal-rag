#!/usr/bin/env python3
"""
Corpus-Wide Blanket and Referential Disposition Extractor.
Scans all indexed articles in data/store/legal_rag.db,
detects blankett norms (regulations, government decrees) and verweisende norms,
and outputs a structured report and candidate list for the Regulations catalog.
"""

import json
import logging
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.nlp.blanket_analyzer import BlanketAnalyzer, BlanketMatch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def extract_all():
    db_path = Path("data/store/legal_rag.db")
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT canonical_id, json_extract(json_data, '$.metadata.law_id'), 
               json_extract(json_data, '$.translations.uz')
        FROM articles_metadata
    """)
    rows = c.fetchall()
    logger.info(f"Loaded {len(rows)} articles from {db_path} for blanket disposition analysis.")

    named_counts = Counter()
    gov_counts = Counter()
    statutory_counts = Counter()

    article_matches: Dict[str, List[Dict]] = {}
    total_blanket_articles = 0

    for canonical_id, law_id, text_uz in rows:
        if not text_uz:
            continue

        matches = BlanketAnalyzer.analyze_article_text(text_uz, law_slug=law_id or "")
        if matches:
            total_blanket_articles += 1
            article_matches[canonical_id] = [m.model_dump() for m in matches]

            for m in matches:
                if m.disposition_type == "blanket_named_regulation":
                    named_counts[m.target_phrase.lower()] += 1
                elif m.disposition_type == "blanket_government":
                    gov_counts[m.target_phrase.lower()] += 1
                elif m.disposition_type == "statutory_reference":
                    statutory_counts[m.target_phrase.lower()] += 1

    report = {
        "total_analyzed_articles": len(rows),
        "total_articles_with_blanket_or_refs": total_blanket_articles,
        "percentage": round((total_blanket_articles / len(rows)) * 100, 2) if rows else 0,
        "top_named_regulations": named_counts.most_common(20),
        "top_government_blankets": gov_counts.most_common(20),
        "top_statutory_references": statutory_counts.most_common(20),
    }

    out_file = Path("data/laws_catalog/blanket_dispositions_summary.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info(f"Blanket analysis complete!")
    logger.info(f"Articles with blanket/ref dispositions: {total_blanket_articles} / {len(rows)} ({report['percentage']}%)")
    logger.info("Top 5 Named Regulations referenced:")
    for name, cnt in named_counts.most_common(5):
        logger.info(f" - {name}: {cnt} references")

    logger.info("Top 5 Government Blanket Phrases:")
    for phrase, cnt in gov_counts.most_common(5):
        logger.info(f" - {phrase}: {cnt} references")


if __name__ == "__main__":
    extract_all()
