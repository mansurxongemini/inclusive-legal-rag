"""
Embedding chunks for legal units.

A whole article is embedded when it is short; long articles are split at paragraph boundaries so that a
question about one paragraph of a 12 000-character article is not diluted by the other forty paragraphs.
Every chunk is prefixed with the act and article labels so that it stays interpretable on its own.
"""
import re
from typing import List

from src.schema.canonical import CanonicalArticle

MAX_CHARS = 1700
OVERLAP_CHARS = 180
MAX_CHUNKS_PER_ARTICLE = 14


def _header(article: CanonicalArticle, language: str) -> str:
    law_title = article.get_law_title(language) or article.metadata.law_number
    parts = [law_title, article.metadata.article_number]
    title = article.get_title(language)
    head = " | ".join(p for p in parts if p)
    return f"{head}. {title}".strip() if title else head


def _paragraphs(text: str) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    out: List[str] = []
    for p in paras:
        # a single enormous paragraph (e.g. one table row dump) is cut at sentence ends
        while len(p) > MAX_CHARS:
            cut = p.rfind(". ", 0, MAX_CHARS)
            cut = cut + 1 if cut > MAX_CHARS // 2 else MAX_CHARS
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out


def build_chunks(article: CanonicalArticle, language: str) -> List[str]:
    """Texts to embed for one language of one article (never empty when the language has text)."""
    body = (article.translations.get(language) or "").strip()
    if not body:
        return []
    header = _header(article, language)
    if body.startswith("Hujjat:"):          # legacy synthetic summaries: keep the old behaviour
        return [body[:3200]]

    if len(header) + len(body) + 2 <= MAX_CHARS:
        return [f"{header}\n{body}"]

    chunks: List[str] = []
    current = ""
    for para in _paragraphs(body):
        if current and len(header) + len(current) + len(para) + 2 > MAX_CHARS:
            chunks.append(current)
            tail = current[-OVERLAP_CHARS:]
            tail = tail[tail.find(" ") + 1:] if " " in tail else tail
            current = tail + "\n" + para
        else:
            current = f"{current}\n{para}" if current else para
        if len(chunks) >= MAX_CHUNKS_PER_ARTICLE:
            break
    if current and len(chunks) < MAX_CHUNKS_PER_ARTICLE:
        chunks.append(current)
    return [f"{header}\n{c}" for c in chunks]
