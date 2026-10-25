"""
The part of a long unit that answers the question.

Jev reads JEV_RERANK_CHARS of every candidate and the LLM MAX_CONTEXT_CHARS_PER_ARTICLE of every context. Cutting a
long unit (a code article of 50 000 characters, an annex table) at its beginning hides the paragraph the question is
about. Instead the unit is shown as its beginning plus the matched chunk and its neighbours:

* the chunk is the best vector hit of the unit (chunk_index in the vector store), when the hit is in the language
  of the text shown;
* otherwise the chunk sharing the most distinctive query words (stems weighted by 1 / number of chunks containing
  them, so words present everywhere count little).
"""
import re
from functools import lru_cache
from typing import Dict, Iterable, Optional, Tuple

from src.nlp.transliteration import cyrillic_to_latin
from src.schema.canonical import CanonicalArticle
from src.storage.chunking import chunk_layout

_APOSTROPHES = re.compile(r"[ʻʼ‘’`´']")
_WORD = re.compile(r"[^\W\d_]{4,}")


@lru_cache(maxsize=1024)         # the same candidate units are scored for question after question; frozen: the result is shared
def _stems(text: str) -> frozenset:
    """5-letter prefixes of the words (Latin and Cyrillic), apostrophes dropped: bo'lgan ~ bo‘lganlar."""
    return frozenset(w[:5] for w in _WORD.findall(_APOSTROPHES.sub("", (text or "").lower())))


def text_language(article: CanonicalArticle, language: str) -> str:
    """Language whose text article.get_text(language) returns (same fallback order: language, uz, ru)."""
    for lang in (language, "uz", "ru"):
        if (article.translations.get(lang) or "").strip():
            return lang
    return next(iter(article.translations), language)


def _lexical_chunk(texts, query_stems: set) -> Optional[int]:
    chunk_stems = [_stems(t) for t in texts]
    df: Dict[str, int] = {}
    for stems in chunk_stems:
        for s in stems & query_stems:
            df[s] = df.get(s, 0) + 1
    best, best_score = None, 0.0
    for idx, stems in enumerate(chunk_stems):
        score = sum(1.0 / df[s] for s in stems & query_stems)
        if score > best_score:
            best, best_score = idx, score
    return best


def focus_chunks(
    article: CanonicalArticle,
    query: str,
    languages: Iterable[str],
    vector_chunk: Optional[Tuple[str, int]] = None,
) -> Dict[str, int]:
    """{text language: chunk index} for the languages a reader will see; empty for single-chunk units."""
    focus: Dict[str, int] = {}
    query_stems = set(_stems(query))
    if re.search(r"[а-яёўғқҳ]", query, re.IGNORECASE):
        query_stems |= _stems(cyrillic_to_latin(query))      # a Cyrillic Uzbek question against Latin text
    for lang in {text_language(article, l) for l in languages}:
        layout = chunk_layout(article, lang)
        if layout is None or len(layout.spans) < 2:
            continue
        if vector_chunk and vector_chunk[0] == lang and 0 <= vector_chunk[1] < len(layout.spans):
            focus[lang] = vector_chunk[1]
            continue
        idx = _lexical_chunk(layout.texts, query_stems)
        if idx is not None:
            focus[lang] = idx
    return focus


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut.rsplit(" ", 1)[0] if " " in cut else cut


def focused_text(
    article: CanonicalArticle,
    language: str,
    focus: Optional[Dict[str, int]],
    budget: int,
    marker: str = "[...]",
) -> str:
    """
    Text of the unit in `language` that fits `budget` characters. A unit that fits is returned whole; a long one
    without a focus chunk is cut at its beginning (the old behaviour); otherwise: the beginning (a quarter of the
    budget), the focus chunk, then its neighbours while they fit. Omitted parts are shown as `marker`.
    """
    text = article.get_text(language)
    if len(text) <= budget:
        return text
    lang = text_language(article, language)
    idx = (focus or {}).get(lang)
    layout = chunk_layout(article, lang) if idx is not None else None
    if layout is None or not 0 <= idx < len(layout.spans):
        return f"{_cut(text, budget)} {marker}"

    paras = layout.paragraphs
    start, end = layout.spans[idx]
    pieces: Dict[int, str] = {}
    partial = set()
    used = 0

    def add(i: int, room: int) -> bool:
        nonlocal used
        para = paras[i]
        if len(para) + 1 <= room:
            pieces[i] = para
            used += len(para) + 1
            return True
        if room > 80:
            pieces[i] = _cut(para, room - 1)
            partial.add(i)
            used += len(pieces[i]) + 1
        return False

    # beginning of the unit: what it is about (preamble sentence, table header, first paragraph)
    head_budget = budget // 4
    i = 0
    while i < start and add(i, head_budget - used):
        i += 1

    # the matched chunk
    whole_chunk = all(add(j, budget - used) for j in range(start, end))

    # neighbours, next one first (a rule is usually continued below), while they fit
    lo, hi = start - 1, end
    while whole_chunk:
        grew = False
        if hi < len(paras) and hi not in pieces and len(paras[hi]) + 1 <= budget - used:
            add(hi, budget - used)
            hi += 1
            grew = True
        if lo >= 0 and lo not in pieces and len(paras[lo]) + 1 <= budget - used:
            add(lo, budget - used)
            lo -= 1
            grew = True
        if not grew:
            break

    out = []
    prev = -1
    for i in sorted(pieces):
        if i != prev + 1 or prev in partial:
            out.append(marker)
        out.append(pieces[i])
        prev = i
    if prev != len(paras) - 1 or prev in partial:
        out.append(marker)
    return "\n".join(out)
