#!/usr/bin/env python3
"""
Benchmark script: Tests 100 diverse, complex Lex.uz documents across all categories
to evaluate multi-annex partitioning, table chunking, multilingual pairing, and ID uniqueness.
"""

import asyncio
import hashlib
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, List

import httpx
from bs4 import BeautifulSoup

from scripts.orchestrate_stage1_ingest import CATEGORY_MAP, build_slug, check_document_active_status
from scripts.ingest_all_laws import parse_act_list_doc
from src.ingestion.universal_engine import DocumentSpec, UniversalParser
from src.schema.canonical import CanonicalArticle

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("benchmark_100")


def sample_100_diverse_documents() -> List[Dict]:
    """Samples 100 diverse documents spanning various acts and potential edge cases."""
    all_sampled = []
    
    # Target allocations
    targets = {
        "qarorlar": 30,     # Heaviest on multi-annex & complex tables
        "buyruqlar": 20,    # Departmental standards & technical tables
        "farmonlar": 15,    # Major strategic decrees
        "nizomlar": 15,     # Pure regulatory charters
        "tartiblar": 10,    # Procedural regulations
        "oliy_majlis": 5,   # Parliament decisions
        "xalqaro": 5,       # International treaties
    }
    
    for cat_key, quota in targets.items():
        cfg = CATEGORY_MAP.get(cat_key)
        if not cfg:
            continue
        p = Path(cfg["file"])
        if not p.exists():
            continue
        items = parse_act_list_doc(p)
        if not items:
            continue
            
        step = max(1, len(items) // quota)
        chosen = items[::step][:quota]
        for it in chosen:
            it["cat_key"] = cat_key
            it["cat_config"] = cfg
            all_sampled.append(it)

    return all_sampled[:100]


async def test_single_document(
    client: httpx.AsyncClient,
    item: Dict,
    idx: int,
) -> Dict:
    doc_id = item["doc_id"]
    title = item.get("title", "")
    raw_num = item.get("law_number", f"ID_{doc_id}")
    cat_cfg = item["cat_config"]
    slug = build_slug(cat_cfg["prefix"], raw_num, doc_id)
    url = f"https://lex.uz/docs/{doc_id}"

    res = {
        "index": idx,
        "doc_id": doc_id,
        "title": title[:100],
        "category": item["cat_key"],
        "url": url,
        "status": "pending",
        "articles_count": 0,
        "annexes_count": 0,
        "tables_count": 0,
        "table_chunks_count": 0,
        "duplicate_ids": 0,
        "has_ru": False,
        "error": None,
    }

    try:
        resp = await client.get(url, timeout=25)
        if resp.status_code != 200:
            res["status"] = f"http_{resp.status_code}"
            return res

        html_uz = resp.text

        # Check PDF-only
        if "pdfBody" in html_uz and "divCont" not in html_uz:
            res["status"] = "skipped_pdf_only"
            return res

        # Check repealed
        soup_head = BeautifulSoup(html_uz[:12000], "html.parser")
        is_active, status_reason = check_document_active_status(soup_head)
        if not is_active:
            res["status"] = "skipped_repealed"
            res["status_reason"] = status_reason
            return res

        full_soup = BeautifulSoup(html_uz, "html.parser")
        lang_links = UniversalParser.extract_lex_language_links(full_soup)

        html_ru = None
        if "ru" in lang_links:
            try:
                resp_ru = await client.get(lang_links["ru"], timeout=15)
                if resp_ru.status_code == 200:
                    html_ru = resp_ru.text
                    res["has_ru"] = True
            except Exception:
                pass

        spec = DocumentSpec(
            slug=slug,
            category=cat_cfg["category"],
            doc_number=raw_num,
            title_uz=title,
            effective_date="2020-01-01",
            url_uz=url,
            parser_type="regulation_clause" if item["cat_key"] in ["qarorlar", "buyruqlar", "farmonlar", "nizomlar", "tartiblar"] else "statutory_article",
        )

        uz_preview = (full_soup.find(id="divCont") or full_soup).get_text()[:3000].lower()
        is_ru_only = (
            "ҳужжат матни рус тилида" in uz_preview
            or "hujjat matni rus tilida" in uz_preview
            or "акта приводится на русском языке" in uz_preview
        )

        if is_ru_only and html_ru:
            articles = UniversalParser.parse_regulation_clauses(html_ru, spec, html_ru)
            if not articles:
                articles = UniversalParser.parse_statutory_articles(html_ru, spec, html_ru)
        else:
            articles = UniversalParser.parse_regulation_clauses(html_uz, spec, html_ru)
            if not articles:
                articles = UniversalParser.parse_statutory_articles(html_uz, spec, html_ru)

        if not articles:
            res["status"] = "empty_content"
            return res

        # Analyze extracted articles
        res["articles_count"] = len(articles)
        seen_ids = set()
        dups = 0
        tbl_chunks = 0
        annexes = set()

        for a in articles:
            cid = a.canonical_id
            if cid in seen_ids:
                dups += 1
            seen_ids.add(cid)
            if "tbl" in cid:
                tbl_chunks += 1
            if "ilova_" in cid or "sec_" in cid:
                # Extract annex identifier
                m = re.search(r"(?:ilova_\w+|sec_\w+)", cid)
                if m:
                    annexes.add(m.group(0))

        res["duplicate_ids"] = dups
        res["table_chunks_count"] = tbl_chunks
        res["annexes_count"] = len(annexes)

        # Count raw tables in HTML
        soup_tables = BeautifulSoup(html_uz, "html.parser").find_all("table")
        res["tables_count"] = len(soup_tables)

        res["status"] = "success"
        return res

    except Exception as e:
        res["status"] = "exception"
        res["error"] = str(e)
        return res


async def run_benchmark():
    items = sample_100_diverse_documents()
    print(f"🚀 Starting 100-Document Edge-Case Benchmark across {len(items)} sampled acts...")

    results = []
    # Run with controlled concurrency of 10 parallel connections
    limits = httpx.Limits(max_keepalive_connections=15, max_connections=20)
    async with httpx.AsyncClient(limits=limits, headers={"User-Agent": "Mozilla/5.0 (LegalRAG Benchmark)"}) as client:
        # Process in batches of 10
        for i in range(0, len(items), 10):
            batch = items[i:i+10]
            tasks = [test_single_document(client, it, i + idx + 1) for idx, it in enumerate(batch)]
            batch_res = await asyncio.gather(*tasks)
            results.extend(batch_res)
            print(f"  Processed {len(results)}/100 documents...")
            await asyncio.sleep(0.5)

    # Save benchmark JSON
    out_file = Path("data/store/benchmark_100_results.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Aggregate Statistics
    total = len(results)
    success = sum(1 for r in results if r["status"] == "success")
    repealed = sum(1 for r in results if r["status"] == "skipped_repealed")
    pdf_only = sum(1 for r in results if r["status"] == "skipped_pdf_only")
    errors = sum(1 for r in results if r["status"] in ["exception", "http_404", "empty_content"])
    total_articles = sum(r["articles_count"] for r in results)
    total_tables = sum(r["tables_count"] for r in results)
    total_tbl_chunks = sum(r["table_chunks_count"] for r in results)
    total_annexes = sum(r["annexes_count"] for r in results)
    total_dups = sum(r["duplicate_ids"] for r in results)

    print("\n" + "="*50)
    print("📊 100-DOCUMENT BENCHMARK SUMMARY REPORT")
    print("="*50)
    print(f"Total Evaluated: {total}")
    print(f"✅ Success (Fully Parsed & Segmented): {success} ({success/total*100:.1f}%)")
    print(f"⚠️ Repealed / Inactive Acts: {repealed}")
    print(f"📄 PDF-only Acts (HTML pending): {pdf_only}")
    print(f"❌ Failed / Empty Content: {errors}")
    print(f"📑 Total Extracted Articles/Clauses: {total_articles}")
    print(f"📋 Total HTML Tables Found: {total_tables}")
    print(f"🧩 Total Markdown Table Chunks Generated: {total_tbl_chunks}")
    print(f"📎 Total Distinct Annexes/Schedules Handled: {total_annexes}")
    print(f"🚫 Collision / Duplicate ID Count: {total_dups} (Zero duplicates required)")
    print(f"Results saved to: {out_file}")
    print("="*50)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
