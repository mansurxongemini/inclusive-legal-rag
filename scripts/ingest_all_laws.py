#!/usr/bin/env python3
"""
Automated Master Ingestion Engine for all 1,250+ Laws of the Republic of Uzbekistan.
Reads data/qonunlar/act_list.doc, validates active status, parses articles,
pairs with official Lex.uz Russian versions, and indexes into LanceDB & SQLite FTS5.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
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
from src.nlp.transliteration import cyrillic_to_latin, detect_script, normalize_apostrophes
from scripts.ingest_active_codes import check_document_active_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_act_list_doc(file_path: Path) -> List[Dict]:
    """Parses data/qonunlar/act_list.doc into structured law items."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    items = []
    for r in soup.find_all("tr")[1:]:
        cols = [c.get_text().strip() for c in r.find_all(["td", "th"])]
        if len(cols) >= 5:
            idx, req, title, eff_date, link = cols[:5]
            m = re.search(r"/docs/(-?\d+)", link)
            doc_id = m.group(1).lstrip("-") if m else None

            req_parts = [p.strip() for p in req.split(",") if p.strip()]
            law_num = req_parts[0] if req_parts else ""

            # Slug generation
            clean_num = re.sub(r"[^a-zA-Z0-9]+", "_", law_num).strip("_").lower()
            slug = f"law_{clean_num}" if clean_num else f"law_doc_{doc_id}"

            items.append({
                "index": int(idx) if idx.isdigit() else len(items) + 1,
                "slug": slug,
                "law_number": law_num,
                "raw_requisites": req,
                "title": title,
                "effective_date": eff_date,
                "url": link,
                "doc_id": doc_id,
            })
    return items


def parse_russian_clauses(html_text: str) -> Dict[str, Tuple[str, str]]:
    """Extracts Russian articles: art_num -> (title, body)."""
    soup = BeautifulSoup(html_text, "html.parser")
    for el in soup.find_all("div", class_=["lx_elem2", "INDEXES_ON_REF", "COMMENT", "CHANGES_ORIGINS"]):
        el.decompose()

    div_cont = soup.find("div", id="divCont") or soup.find("div", class_="doc_content") or soup.find("body")
    if not div_cont:
        return {}

    # Convert sup tags to hyphenated numbers (e.g. 18<sup>1</sup> -> 18-1)
    for sup in div_cont.find_all("sup"):
        stxt = sup.get_text().strip()
        if stxt.isdigit():
            sup.replace_with(f"-{stxt}")
        else:
            sup.decompose()

    art_regex = re.compile(r"^(?:статья|модда|modda)\s*(\d+(?:-\d+)*)[\.\s:]*(.*)$", re.IGNORECASE)
    articles = {}
    cur_num = None
    cur_title = ""
    cur_p = []

    for ch in div_cont.find_all("div", recursive=False):
        txt = " ".join(ch.get_text().split())
        if not txt:
            continue
        m = art_regex.match(txt)
        if m:
            if cur_num:
                articles[cur_num] = (cur_title, "\n\n".join(cur_p))
            cur_num = m.group(1)
            cur_title = m.group(2).strip()
            cur_p = []
            continue
        if cur_num:
            if not txt.startswith("Ҳужжатга таклиф") and not txt.startswith("Отправить предложение"):
                cur_p.append(txt)

    if cur_num:
        articles[cur_num] = (cur_title, "\n\n".join(cur_p))

    return articles


def parse_law_articles(
    html_text: str,
    slug: str,
    law_number: str,
    law_title: str,
    effective_date: str,
    source_url: str,
) -> List[CanonicalArticle]:
    """Parses Uzbek law HTML into CanonicalArticle models."""
    soup = BeautifulSoup(html_text, "html.parser")
    for el in soup.find_all("div", class_=["lx_elem2", "INDEXES_ON_REF", "COMMENT", "CHANGES_ORIGINS"]):
        el.decompose()

    div_cont = soup.find("div", id="divCont") or soup.find("div", class_="doc_content") or soup.find("body")
    if not div_cont:
        return []

    # Convert sup tags to hyphenated numbers (e.g. 18<sup>1</sup> -> 18-1)
    for sup in div_cont.find_all("sup"):
        stxt = sup.get_text().strip()
        if stxt.isdigit():
            sup.replace_with(f"-{stxt}")
        else:
            sup.decompose()

    art_regex = re.compile(r"^(\d+(?:-\d+)*)\s*[-–—]?\s*(?:модда|modda)[\.\s:]*(.*)$", re.IGNORECASE | re.DOTALL)
    children = div_cont.find_all("div", recursive=False)

    raw_articles = []
    cur_num = None
    cur_title = ""
    cur_p = []

    for ch in children:
        classes = ch.get("class", [])
        if "INDEXES_ON_REF" in classes or "COMMENT" in classes:
            continue
        txt = " ".join(ch.get_text().split())
        if not txt:
            continue

        m = art_regex.match(txt)
        if m:
            if cur_num:
                raw_articles.append((cur_num, cur_title, cur_p))
            cur_num = m.group(1)
            cur_title = " ".join(m.group(2).split())
            cur_p = []
            continue

        if cur_num and ("ACT_TEXT" in classes or not classes):
            if not txt.startswith("Ҳужжатга таклиф"):
                cur_p.append(txt)

    if cur_num:
        raw_articles.append((cur_num, cur_title, cur_p))

    # If no numbered articles found, treat the whole document as Article 1
    if not raw_articles:
        body_p = []
        for ch in children:
            if "ACT_TEXT" in ch.get("class", []):
                t = " ".join(ch.get_text().split())
                if t and not t.startswith("Ҳужжатга таклиф"):
                    body_p.append(t)
        if body_p:
            raw_articles.append(("1", law_title, body_p))

    seen = set()
    articles: List[CanonicalArticle] = []

    for art_num, raw_title, paragraphs in raw_articles:
        if art_num in seen:
            continue
        seen.add(art_num)

        full_raw = "\n\n".join(paragraphs) if paragraphs else raw_title
        is_cyrillic = detect_script(raw_title + " " + full_raw) == "cyrillic"
        if is_cyrillic:
            title_uz = cyrillic_to_latin(raw_title)
            body_uz = cyrillic_to_latin(full_raw)
            title_ru = raw_title
            body_ru = full_raw
        else:
            title_uz = normalize_apostrophes(raw_title)
            body_uz = normalize_apostrophes(full_raw)
            title_ru = title_uz
            body_ru = body_uz

        is_rep = "ўз кучини йўқотган" in full_raw.lower() or "o'z kuchini yo'qotgan" in body_uz.lower()
        status = ArticleStatus.REPEALED if is_rep else ArticleStatus.ACTIVE

        points = []
        pt_pattern = re.compile(r"^\s*(\d+)[\.\)]\s+(.*)$")
        for idx, p in enumerate(paragraphs, 1):
            clean_p = cyrillic_to_latin(p) if is_cyrillic else normalize_apostrophes(p)
            pm = pt_pattern.match(clean_p)
            pid = pm.group(1) if pm else str(idx)
            ptext = pm.group(2) if pm else clean_p
            points.append(ArticlePoint(
                point_id=pid,
                text={"uz": ptext, "ru": p if is_cyrillic else "", "en": ""}
            ))

        hasher = hashlib.sha256()
        hasher.update(body_uz.encode("utf-8"))
        source_hash = f"sha256:{hasher.hexdigest()}"

        meta = ArticleMetadata(
            law_id=slug,
            law_title={"uz": law_title, "ru": law_title, "en": law_title},
            law_number=law_number,
            chapter_number=None,
            article_number=f"{art_num}-modda",
            article_title={"uz": title_uz if title_uz else f"{art_num}-modda", "ru": title_ru, "en": title_uz},
            source_url=source_url,
            effective_date=effective_date,
            last_verified_date="2026-09-27",
            source_hash=source_hash,
            status=status,
            category="general_legislation",
            disability_types=["general"],
            beneficiary_type=["citizen", "legal_entity", "state_body"],
            cross_references=[],
            embedding_model_version="bge-m3-2025-11-18",
        )

        safe_art_suffix = str(art_num).replace("-", "_")
        articles.append(CanonicalArticle(
            canonical_id=f"{slug}_art_{safe_art_suffix}",
            schema_version="1.1",
            metadata=meta,
            points=points,
            translations={"uz": body_uz, "ru": body_ru, "en": ""},
            translation_provenance={
                "uz": TranslationProvenanceType.OFFICIAL,
                "ru": TranslationProvenanceType.OFFICIAL if is_cyrillic else TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                "en": TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
            }
        ))

    return articles


async def ingest_single_law(
    http_client: httpx.AsyncClient,
    store: HybridStore,
    openrouter_client: OpenRouterClient,
    item: Dict,
    laws_dir: Path,
    batch_size: int = 25,
) -> Dict:
    slug = item["slug"]
    doc_id = item["doc_id"]
    law_number = item["law_number"]
    law_title = item["title"]
    eff_date = item["effective_date"]
    url = f"https://lex.uz/docs/{doc_id}"
    cache_path = laws_dir / f"{slug}.json"

    # Check if already cached and indexed
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data:
                first_id = data[0].get("canonical_id")
                if store.get_article(first_id):
                    return {"slug": slug, "status": "already_indexed", "articles": len(data)}
        except Exception:
            pass

    # 1. Fetch Uzbek HTML
    resp = await http_client.get(url)
    if resp.status_code != 200:
        return {"slug": slug, "status": "failed_fetch", "error": f"HTTP {resp.status_code}"}

    # 2. Check active status
    soup = BeautifulSoup(resp.text[:10000], "html.parser")
    is_active, status_reason = check_document_active_status(soup)
    if not is_active:
        return {"slug": slug, "status": "skipped_repealed", "reason": status_reason}

    # 3. Parse into canonical articles
    articles = parse_law_articles(
        html_text=resp.text,
        slug=slug,
        law_number=law_number,
        law_title=law_title,
        effective_date=eff_date,
        source_url=url,
    )

    if not articles:
        return {"slug": slug, "status": "empty_articles", "articles": 0}

    # 4. Check for official Russian version
    m_ru = re.search(r'onclick=\"openUrl\(\'([^\']+)\'\)\"\s+title=\"На русском\"', resp.text)
    if m_ru:
        ru_doc_path = m_ru.group(1)
        ru_url = f"https://lex.uz{ru_doc_path}" if ru_doc_path.startswith("/") else f"https://lex.uz/docs/{ru_doc_path}"
        try:
            resp_ru = await http_client.get(ru_url)
            if resp_ru.status_code == 200:
                ru_articles = parse_russian_clauses(resp_ru.text)
                for art in articles:
                    num_m = re.search(r"(\d+)", art.metadata.article_number)
                    if num_m and num_m.group(1) in ru_articles:
                        ru_t, ru_b = ru_articles[num_m.group(1)]
                        art.translations["ru"] = ru_b if ru_b else ru_t
                        art.metadata.article_title["ru"] = ru_t
                        art.translation_provenance["ru"] = TranslationProvenanceType.OFFICIAL
        except Exception as e:
            logger.warning(f"[{slug}] Could not enrich Russian version: {e}")

    # 5. Save canonical JSON cache
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump([a.model_dump() for a in articles], f, ensure_ascii=False, indent=2)

    # 6. Index into LanceDB and SQLite FTS5 using batch indexing
    indexed = await store.index_articles_batch(articles, client=openrouter_client, batch_size=batch_size)

    return {"slug": slug, "status": "success", "articles": indexed}


async def main():
    parser = argparse.ArgumentParser(description="Ingest All Laws of Uzbekistan")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of laws to process (0 = all 1,251)")
    parser.add_argument("--batch-size", type=int, default=25, help="Batch size for vector embeddings (default: 25)")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between document fetches (default: 0.5s)")
    args = parser.parse_args()

    act_list_file = Path("data/qonunlar/act_list.doc")
    if not act_list_file.exists():
        logger.error(f"File not found: {act_list_file}")
        sys.exit(1)

    laws_dir = Path("data/laws_catalog/laws")
    laws_dir.mkdir(parents=True, exist_ok=True)

    items = parse_act_list_doc(act_list_file)
    logger.info(f"Loaded {len(items)} laws from {act_list_file}")

    if args.limit > 0:
        items = items[:args.limit]
        logger.info(f"Limited processing to first {len(items)} laws.")

    store = HybridStore()
    openrouter_client = OpenRouterClient()
    logger.info(f"Initial store count: {store.count()} articles.")

    headers = {
        "User-Agent": "UzbekistanLegalRAG/1.0 (Government & Citizen Legal Access Research; contact@legal-rag.uz)",
        "Accept-Language": "uz,ru;q=0.9",
    }

    progress_file = Path("data/laws_catalog/laws_progress.json")
    stats = {"total": len(items), "success": 0, "skipped_repealed": 0, "already_indexed": 0, "errors": 0, "articles": 0}

    start_time = time.time()
    async with httpx.AsyncClient(timeout=35.0, follow_redirects=True, headers=headers) as http_client:
        for idx, item in enumerate(items, 1):
            slug = item["slug"]
            law_num = item["law_number"]
            title = item["title"][:50]

            try:
                res = await ingest_single_law(
                    http_client=http_client,
                    store=store,
                    openrouter_client=openrouter_client,
                    item=item,
                    laws_dir=laws_dir,
                    batch_size=args.batch_size,
                )
                status = res["status"]
                arts = res.get("articles", 0)

                if status == "success":
                    stats["success"] += 1
                    stats["articles"] += arts
                    logger.info(f"[{idx}/{len(items)}] SUCCESS {law_num} ({slug}): {arts} articles indexed.")
                elif status == "already_indexed":
                    stats["already_indexed"] += 1
                    logger.info(f"[{idx}/{len(items)}] SKIP_ALREADY_INDEXED {law_num} ({slug})")
                elif status == "skipped_repealed":
                    stats["skipped_repealed"] += 1
                    logger.info(f"[{idx}/{len(items)}] SKIP_REPEALED {law_num}: {res.get('reason')}")
                else:
                    stats["errors"] += 1
                    logger.warning(f"[{idx}/{len(items)}] {status} {law_num}: {res.get('error', '')}")

            except Exception as e:
                stats["errors"] += 1
                logger.error(f"[{idx}/{len(items)}] EXCEPTION {law_num}: {e}", exc_info=False)

            # Periodic progress checkpoint
            if idx % 25 == 0 or idx == len(items):
                with open(progress_file, "w", encoding="utf-8") as pf:
                    json.dump({"stats": stats, "processed_index": idx, "elapsed_s": time.time() - start_time}, pf, indent=2)
                logger.info(f"-- Checkpoint [{idx}/{len(items)}] -- Store Count: {store.count()} | Elapsed: {time.time()-start_time:.1f}s")

            await asyncio.sleep(args.delay)

    total_time = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"ALL LAWS INGESTION COMPLETED in {total_time:.1f}s ({total_time/60:.1f}m)")
    logger.info(f"Summary: {json.dumps(stats, indent=2)}")
    logger.info(f"Final store count: {store.count()} articles.")


if __name__ == "__main__":
    asyncio.run(main())
