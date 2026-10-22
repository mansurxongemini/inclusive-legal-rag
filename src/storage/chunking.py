"""
Embedding chunks for legal units.

A whole article is embedded when it is short; long articles are split at paragraph boundaries so that a
question about one paragraph of a 12 000-character article is not diluted by the other forty paragraphs.
Every chunk is prefixed with the act and article labels so that it stays interpretable on its own.
"""
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.schema.canonical import CanonicalArticle

MAX_CHARS = 1700
OVERLAP_CHARS = 180
MAX_CHUNKS_PER_ARTICLE = 14
MAX_CONTEXT_LINE_CHARS = 240


def _cap_context_line(text: str, limit: int = MAX_CONTEXT_LINE_CHARS) -> str:
    """Caps text at limit characters, cutting at a word boundary and appending '…'."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if text[limit] == " ":
        return cut.rstrip() + "…"
    last_space = cut.rfind(" ")
    if last_space > 0:
        return cut[:last_space].rstrip() + "…"
    return cut + "…"


def has_context_header(article: CanonicalArticle) -> bool:
    """Returns True when chapter_number or annex_title is non-empty."""
    if not article or not hasattr(article, "metadata"):
        return False
    ch = (article.metadata.chapter_number or "").strip()
    ax = (article.metadata.annex_title or "").strip()
    return bool(ch or ax)


def _header(article: CanonicalArticle, language: str) -> str:
    law_title = article.get_law_title(language) or article.metadata.law_number
    parts = [law_title, article.metadata.article_number]
    title = article.get_title(language)
    head = " | ".join(p for p in parts if p)
    first_line = f"{head}. {title}".strip() if title else head

    chapter = (article.metadata.chapter_number or "").strip()
    annex = (article.metadata.annex_title or "").strip()

    if not chapter and not annex:
        return first_line

    lines = [first_line]

    uz_law_title = (article.get_law_title("uz") or "").strip()
    curr_law_title = (law_title or "").strip()

    def _contained_in_law(line_text: str) -> bool:
        if curr_law_title and line_text in curr_law_title:
            return True
        if uz_law_title and line_text in uz_law_title:
            return True
        return False

    if chapter and not _contained_in_law(chapter):
        lines.append(_cap_context_line(chapter))

    if annex:
        in_chapter = bool(chapter and annex in chapter)
        if not in_chapter and not _contained_in_law(annex):
            lines.append(_cap_context_line(annex))

    return "\n".join(lines)


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


@dataclass
class ChunkLayout:
    """How one language of an article is cut into embedding chunks.

    texts[i] is the text of chunk i (header included); spans[i] = (start, end) are the indices of the paragraphs
    that chunk i adds (the overlap carried over from the previous chunk is not part of its span). The layout covers
    the whole text; only the first MAX_CHUNKS_PER_ARTICLE chunks are embedded (build_chunks). The vector store keeps
    i as chunk_index, so a vector hit can be traced back to its paragraphs.
    """
    paragraphs: List[str]
    texts: List[str]
    spans: List[Tuple[int, int]]


def chunk_layout(article: CanonicalArticle, language: str) -> Optional[ChunkLayout]:
    """Chunk texts and paragraph spans for one language of one article (None when the language has no text)."""
    body = (article.translations.get(language) or "").strip()
    if not body:
        return None
    paragraphs = _paragraphs(body)
    header = _header(article, language)
    if body.startswith("Hujjat:"):          # legacy synthetic summaries: keep the old behaviour
        return ChunkLayout(paragraphs, [body[:3200]], [(0, len(paragraphs))])

    if len(header) + len(body) + 2 <= MAX_CHARS:
        return ChunkLayout(paragraphs, [f"{header}\n{body}"], [(0, len(paragraphs))])

    chunks: List[str] = []
    spans: List[Tuple[int, int]] = []
    current = ""
    start = 0
    for i, para in enumerate(paragraphs):
        if current and len(header) + len(current) + len(para) + 2 > MAX_CHARS:
            chunks.append(current)
            spans.append((start, i))
            tail = current[-OVERLAP_CHARS:]
            tail = tail[tail.find(" ") + 1:] if " " in tail else tail
            current = tail + "\n" + para
            start = i
        else:
            current = f"{current}\n{para}" if current else para
    if current:
        chunks.append(current)
        spans.append((start, len(paragraphs)))
    return ChunkLayout(paragraphs, [f"{header}\n{c}" for c in chunks], spans)


def build_chunks(article: CanonicalArticle, language: str) -> List[str]:
    """Texts to embed for one language of one article (never empty when the language has text)."""
    layout = chunk_layout(article, language)
    return layout.texts[:MAX_CHUNKS_PER_ARTICLE] if layout else []
