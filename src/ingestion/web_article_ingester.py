#!/usr/bin/env python3
"""
Web Article & Legal Commentary Ingester.
Allows users to enter ANY URL (e.g. from Norma.uz, Advice.uz, Minjust.uz, Kun.uz, Gazeta.uz),
extracts clean text, performs smart structural chunking, identifies referenced laws,
and indexes into the Hybrid Legal Store under 'commentary'.
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.schema.canonical import (
    CanonicalArticle,
    ArticleMetadata,
    ArticlePoint,
    ArticleStatus,
    CrossReference,
    RefType,
    TranslationProvenanceType,
)
from src.nlp.transliteration import cyrillic_to_latin, detect_script, normalize_apostrophes
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient
from src.ingestion.url_safety import assert_public_http_url, httpx_public_request_hook

logger = logging.getLogger(__name__)

DESKTOP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "uz,ru;q=0.9,en;q=0.8",
}

# Regex to detect referenced legislation in article text
LEGAL_REF_PATTERNS = [
    re.compile(r"(?:O[ʻ'`‘]?RQ|ЎРҚ)[-\s]?(\d+)", re.I),
    re.compile(r"(?:PF|ПФ)[-\s]?(\d+)", re.I),
    re.compile(r"(?:PQ|ПҚ)[-\s]?(\d+)", re.I),
    re.compile(r"(?:VMQ|ВМҚ)[-\s]?(\d+)", re.I),
    re.compile(r"(\d+)[-\s]*(?:modda|модда)", re.I),
    re.compile(r"(Mehnat|Soliq|Jinoyat|Fuqarolik|Bojxona|Oila|Uy[- ]joy|Yer)\s+kodeks[a-z]*", re.I),
    re.compile(r"(Меҳнат|Солиқ|Жиноят|Фуқаролик|Божхона|Оила|Уй[- ]жой|Ер)\s+кодекс[а-я]*", re.I),
]


def extract_referenced_laws(text: str) -> List[str]:
    """Finds cited legal acts and articles within unstructured article text."""
    refs = set()
    for pat in LEGAL_REF_PATTERNS:
        for m in pat.finditer(text):
            refs.add(m.group(0).strip())
    return sorted(list(refs))


class WebArticleIngester:
    """Intelligent ingester for unstructured legal articles, advice, and expert commentaries."""

    @staticmethod
    def clean_html(soup: BeautifulSoup) -> BeautifulSoup:
        """Removes non-content elements, ads, scripts, navbars, and widgets."""
        for tag in soup.find_all([
            "script", "style", "nav", "header", "footer", "aside", "form",
            "iframe", "noscript", "svg"
        ]):
            tag.decompose()

        for tag in soup.find_all(attrs={"class": lambda c: c and any(k in str(c).lower() for k in [
            "banner", "advert", "sidebar", "social", "share", "comments",
            "footer", "menu", "nav", "widget", "related", "popular", "tags"
        ])}):
            tag.decompose()

        for tag in soup.find_all(attrs={"id": lambda i: i and any(k in str(i).lower() for k in [
            "banner", "advert", "sidebar", "social", "comments", "footer", "menu", "nav"
        ])}):
            tag.decompose()

        return soup

    @classmethod
    async def fetch_page(cls, url: str, timeout: float = 20.0) -> Tuple[str, str]:
        """Fetches raw HTML and resolves final URL (public hosts only, redirects included)."""
        await asyncio.to_thread(assert_public_http_url, url)
        async with httpx.AsyncClient(
            headers=DESKTOP_HEADERS,
            follow_redirects=True,
            timeout=timeout,
            event_hooks={"request": [httpx_public_request_hook]},
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"Saytga ulanib bo'lmadi: HTTP {resp.status_code} ({url})")
            return resp.text, str(resp.url)

    @classmethod
    def parse_article_metadata(cls, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extracts title, publication date, source domain, and author."""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.replace("www.", "")

        # Title extraction hierarchy
        title = ""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text().strip()
        elif soup.find("title"):
            title = soup.find("title").get_text().strip()

        # Date extraction
        pub_date = ""
        meta_date = (
            soup.find("meta", property="article:published_time") or
            soup.find("meta", property="og:pubdate") or
            soup.find("meta", attrs={"name": "date"})
        )
        if meta_date and meta_date.get("content"):
            pub_date = meta_date["content"][:10]
        else:
            time_tag = soup.find("time")
            if time_tag and time_tag.get("datetime"):
                pub_date = time_tag["datetime"][:10]
            elif time_tag:
                pub_date = time_tag.get_text().strip()[:10]

        if not pub_date:
            date_match = re.search(r"\b(\d{2}[./-]\d{2}[./-]\d{4}|\d{4}[./-]\d{2}[./-]\d{2})\b", soup.get_text())
            if date_match:
                pub_date = date_match.group(1)
            else:
                pub_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Author extraction
        author = ""
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            author = meta_author["content"].strip()

        return {
            "title": title or "Huquqiy tushuntirish maqolasi",
            "domain": domain,
            "published_date": pub_date,
            "author": author,
            "url": url,
        }

    @classmethod
    def extract_and_chunk_article(
        cls,
        soup: BeautifulSoup,
        meta: Dict[str, Any],
        max_chunk_chars: int = 1200,
        min_chunk_chars: int = 250,
    ) -> List[Dict[str, Any]]:
        """
        Smart structural chunker designed for freeform legal articles:
        - Segments by subheadings (h2, h3, h4) and Q&A blocks.
        - Preserves semantic context and article title in every chunk.
        - Automatically identifies cited laws and articles.
        """
        clean_soup = cls.clean_html(soup)

        # Find main content container
        content_container = (
            clean_soup.find("article") or
            clean_soup.find("main") or
            clean_soup.find(class_=lambda c: c and any(k in str(c).lower() for k in ["article-body", "content", "entry-content", "post-content", "news-text", "detail-body"])) or
            clean_soup.find("body")
        )
        if not content_container:
            content_container = clean_soup

        # Extract semantic blocks (headings + paragraphs + lists)
        blocks = []
        for el in content_container.find_all(["h2", "h3", "h4", "h5", "p", "li", "blockquote"]):
            txt = " ".join(el.get_text().split()).strip()
            if not txt or len(txt) < 15:
                continue
            is_heading = el.name in ["h2", "h3", "h4", "h5"]
            blocks.append({"type": "heading" if is_heading else "text", "text": txt})

        if not blocks:
            # Fallback to plain paragraphs
            full_text = " ".join(content_container.get_text().split()).strip()
            if len(full_text) > 50:
                blocks = [{"type": "text", "text": full_text}]

        chunks = []
        current_heading = "Umumiy tushuntirish"
        current_buffer = []
        current_len = 0

        for b in blocks:
            if b["type"] == "heading":
                # Flush previous buffer if large enough
                if current_len >= min_chunk_chars:
                    full_chunk_text = "\n\n".join(current_buffer)
                    chunks.append({
                        "heading": current_heading,
                        "text": full_chunk_text,
                        "refs": extract_referenced_laws(full_chunk_text),
                    })
                    current_buffer = []
                    current_len = 0
                current_heading = b["text"]
            else:
                current_buffer.append(b["text"])
                current_len += len(b["text"])
                if current_len >= max_chunk_chars:
                    full_chunk_text = "\n\n".join(current_buffer)
                    chunks.append({
                        "heading": current_heading,
                        "text": full_chunk_text,
                        "refs": extract_referenced_laws(full_chunk_text),
                    })
                    current_buffer = []
                    current_len = 0

        # Flush remaining buffer
        if current_buffer:
            full_chunk_text = "\n\n".join(current_buffer)
            chunks.append({
                "heading": current_heading,
                "text": full_chunk_text,
                "refs": extract_referenced_laws(full_chunk_text),
            })

        return chunks

    @classmethod
    async def process_and_index_url(
        cls,
        url: str,
        store: HybridStore,
        client: OpenRouterClient,
        custom_title: Optional[str] = None,
        custom_category: str = "commentary",
    ) -> Dict[str, Any]:
        """
        Full pipeline: Fetch -> Metadata Extraction -> Smart Chunking -> Transliteration -> Hybrid Indexing.
        """
        raw_html, final_url = await cls.fetch_page(url)
        soup = BeautifulSoup(raw_html, "html.parser")
        meta = cls.parse_article_metadata(soup, final_url)
        if custom_title:
            meta["title"] = custom_title

        chunks = cls.extract_and_chunk_article(soup, meta)
        if not chunks:
            raise ValueError(f"Havoladan mazmunli matn ajratib bo'lmadi: {url}")

        domain_slug = re.sub(r"[^a-zA-Z0-9]+", "_", meta["domain"]).strip("_").lower()
        url_hash = hashlib.sha256(final_url.encode("utf-8")).hexdigest()[:10]
        law_id = f"web_{domain_slug}_{url_hash}"

        canonical_articles: List[CanonicalArticle] = []

        all_detected_refs = set()
        for idx, ch in enumerate(chunks, 1):
            raw_text = ch["text"]
            is_cyrillic = detect_script(raw_text) == "cyrillic"
            text_uz = cyrillic_to_latin(raw_text) if is_cyrillic else normalize_apostrophes(raw_text)
            text_ru = raw_text if is_cyrillic else ""

            heading_uz = cyrillic_to_latin(ch["heading"]) if is_cyrillic else ch["heading"]
            article_number = f"Qism {idx}"

            # Context-enriched full chunk text for semantic retrieval
            enriched_text = f"[{meta['domain']} | {meta['title']} | {heading_uz}]\n\n{text_uz}"

            hasher = hashlib.sha256()
            hasher.update(enriched_text.encode("utf-8"))
            source_hash = f"sha256:{hasher.hexdigest()}"

            cross_refs = []
            for ref in ch["refs"]:
                all_detected_refs.add(ref)
                cross_refs.append(CrossReference(
                    target_law_id="",
                    target_article=ref,
                    ref_type=RefType.REFERS_TO,
                    context_snippet=f"{meta['domain']} tahlili: {ref}",
                ))

            art_meta = ArticleMetadata(
                law_id=law_id,
                law_title={
                    "uz": meta["title"],
                    "ru": meta["title"],
                    "en": meta["title"],
                },
                law_number=meta["domain"],
                chapter_number=None,
                article_number=article_number,
                article_title={
                    "uz": heading_uz[:90],
                    "ru": ch["heading"][:90],
                    "en": heading_uz[:90],
                },
                source_url=final_url,
                effective_date=meta["published_date"],
                last_verified_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                source_hash=source_hash,
                status=ArticleStatus.ACTIVE,
                category=custom_category,
                disability_types=["general"],
                beneficiary_type=["citizen", "legal_entity", "expert"],
                cross_references=cross_refs,
                embedding_model_version="bge-m3-2025-11-18",
            )

            canonical_articles.append(CanonicalArticle(
                canonical_id=f"{law_id}_part_{idx}",
                schema_version="1.1",
                metadata=art_meta,
                points=[ArticlePoint(point_id=str(idx), text={"uz": text_uz, "ru": text_ru, "en": ""})],
                translations={"uz": enriched_text, "ru": text_ru, "en": ""},
                translation_provenance={
                    "uz": TranslationProvenanceType.OFFICIAL,
                    "ru": TranslationProvenanceType.OFFICIAL if text_ru else TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                    "en": TranslationProvenanceType.MACHINE_TRANSLATED_UNREVIEWED,
                }
            ))

        # Index into LanceDB and SQLite FTS5
        indexed_count = await store.index_articles_batch(canonical_articles, client=client, batch_size=25)

        return {
            "status": "success",
            "law_id": law_id,
            "title": meta["title"],
            "domain": meta["domain"],
            "url": final_url,
            "published_date": meta["published_date"],
            "total_chunks": len(canonical_articles),
            "indexed_count": indexed_count,
            "detected_references": sorted(list(all_detected_refs)),
        }
