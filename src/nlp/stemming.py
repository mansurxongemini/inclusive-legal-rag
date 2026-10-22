"""
Search stems for the full-text query. The index holds inflected words, and the FTS5 wildcard only extends the query
word, so the query has to be cut to a stem: case and plural endings are stripped (bolaning -> bola, nafaqalarni ->
nafaqa) and what is left is capped, because -lik/-ligi alternate the last consonant (nogironlik / nogironligi share
only "nogiron"). Russian words are cut to a prefix (инвалидности ~ инвалидам share "инвалид").
"""
import re

_CYRILLIC = re.compile(r"[а-яёўқғҳ]", re.IGNORECASE)
_SUFFIXES = sorted("""
larning lardan larga larda larni ligini ligida ligiga ligidan lari ligi
ning dagi dan lar ga da ni ki si ri lik i
""".split(), key=len, reverse=True)
LATIN_CAP = 7
CYRILLIC_CAP = 5
MIN_STEM = 4


def search_stem(word: str) -> str:
    """Stem of a word for a prefix query; words with digits, hyphens or underscores (codes, article numbers) are kept."""
    if any(ch.isdigit() for ch in word) or "-" in word or "_" in word:
        return word
    w = word
    if _CYRILLIC.search(w):
        return w[:CYRILLIC_CAP] if len(w) > CYRILLIC_CAP else w
    low = w.lower()
    changed = True
    while changed and len(low) > MIN_STEM + 1:
        changed = False
        for suffix in _SUFFIXES:
            if low.endswith(suffix) and len(low) - len(suffix) >= MIN_STEM:
                low = low[: -len(suffix)]
                changed = True
                break
    return w[: min(len(low), LATIN_CAP)] if len(w) > MIN_STEM else w
