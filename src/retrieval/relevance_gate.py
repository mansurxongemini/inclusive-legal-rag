"""
Decides whether the retrieved evidence is good enough to answer from.

Without a gate the pipeline always hands the top-k nearest articles to the LLM, so a question that is
outside the corpus ("how do I register an LLC?") gets an answer stitched from loosely related provisions.
For a legal-information service for vulnerable people the safe behaviour is an honest "the provided
documents do not cover this" - the same refusal the generator already knows how to produce.

Signals (cheap, no extra model call):
  * cross-encoder (reranker) score of the best context - preferred when available
  * dense similarity of the best chunk (cosine-normalized, 0..1)
  * lexical coverage: share of the question's content words found in the best contexts
  * BM25 agreement: the top context is also found lexically
Thresholds come from settings so they can be calibrated with `scripts/evaluate_retrieval.py`.
"""
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set

from src.config import settings
from src.nlp.transliteration import detect_script, normalize_apostrophes

_STOP = {
    # Uzbek question/function words
    "va", "yoki", "bilan", "uchun", "qanday", "qaysi", "nima", "nega", "kim", "kimlar", "qachon", "qayerda", "bormi",
    "mumkinmi", "kerak", "bu", "shu", "ham", "emas", "lekin", "agar", "haqida", "to'g'risida", "bo'yicha", "dan", "ga",
    "ni", "da", "ning", "bo'lsa", "bo'ladi", "beriladi", "olish", "olishi", "qilish", "qiladi", "tartibi", "tartibda",
    "men", "mening", "bizning", "o'z", "bir", "har", "barcha",
    # Russian
    "и", "или", "в", "на", "для", "как", "что", "кто", "какие", "какой", "есть", "ли", "по", "с", "о", "об", "от", "до",
    "можно", "нужно", "ли",
    # English
    "the", "a", "an", "of", "for", "to", "and", "or", "in", "on", "is", "are", "what", "how", "who", "can", "do", "does",
}


def _tokens(text: str) -> List[str]:
    t = normalize_apostrophes(text or "")
    if detect_script(t) == "cyrillic":
        # Russian stays Cyrillic (matched against Russian text); Uzbek-Cyrillic was already transliterated upstream
        t = t.lower()
    else:
        t = t.lower()
    return [w for w in re.findall(r"[\w'’-]{3,}", t, flags=re.UNICODE) if w not in _STOP]


def _stem(word: str) -> str:
    """Crude agglutination-tolerant stem: first 5 letters ("nogironlarga", "nogironligi" -> "nogir")."""
    return word[:5]


@dataclass
class GateDecision:
    answerable: bool
    reason: str
    confidence: float
    best_vector_score: Optional[float] = None
    lexical_coverage: float = 0.0


class RelevanceGate:
    def __init__(
        self,
        min_vector_score: Optional[float] = None,
        min_lexical_coverage: Optional[float] = None,
    ):
        self.min_vector_score = settings.GATE_MIN_VECTOR_SCORE if min_vector_score is None else min_vector_score
        self.min_lexical_coverage = (
            settings.GATE_MIN_LEXICAL_COVERAGE if min_lexical_coverage is None else min_lexical_coverage
        )

    @staticmethod
    def lexical_coverage(query: str, context_texts: Iterable[str]) -> float:
        q_stems: Set[str] = {_stem(w) for w in _tokens(query)}
        if not q_stems:
            return 1.0
        corpus: Set[str] = set()
        for text in context_texts:
            corpus.update(_stem(w) for w in _tokens(text))
        return len(q_stems & corpus) / len(q_stems)

    def assess(
        self,
        query: str,
        scored: Sequence,            # List[ScoredArticle]
        context_texts: Sequence[str],
        rerank_scores: Sequence[float] = (),
        is_mock: bool = False,
    ) -> GateDecision:
        if not scored or not context_texts:
            return GateDecision(False, "no_candidates", 0.0)
        if is_mock or not settings.GATE_ENABLED:
            return GateDecision(True, "gate_disabled", 1.0)

        # The cross-encoder is by far the best scope detector: on the golden set the weakest in-scope question
        # scores 0.85 while the strongest out-of-scope one reaches 0.66 (dense similarity overlaps: 0.80 vs 0.81).
        if rerank_scores:
            top = max(rerank_scores)
            if top >= settings.GATE_MIN_RERANK_SCORE:
                return GateDecision(True, "reranker_match", top, None, 0.0)
            return GateDecision(False, "low_reranker_score", top, None, 0.0)

        vec_scores = [s.vector_score for s in scored if getattr(s, "vector_score", None) is not None]
        best_vec = max(vec_scores) if vec_scores else None
        coverage = self.lexical_coverage(query, context_texts[:5])
        has_bm25 = any(getattr(s, "bm25_rank", None) is not None and s.bm25_rank <= 3 for s in scored[:5])

        # strong dense match, or good lexical coverage backed by a lexical hit
        if best_vec is not None and best_vec >= self.min_vector_score:
            return GateDecision(True, "dense_match", min(1.0, best_vec), best_vec, coverage)
        if coverage >= self.min_lexical_coverage and has_bm25:
            return GateDecision(True, "lexical_match", coverage, best_vec, coverage)
        if best_vec is None and coverage >= self.min_lexical_coverage:
            return GateDecision(True, "lexical_only", coverage, best_vec, coverage)
        return GateDecision(False, "low_relevance", max(best_vec or 0.0, coverage), best_vec, coverage)


def jev_gate_decision(
    in_scope: Optional[float],
    answerable: Optional[float],
    top_probability: Optional[float],
) -> GateDecision:
    """
    Refuses a question whose scope signal is below GATE_JEV_MIN_IN_SCOPE. A high answerability does not excuse a low scope
    (the Traffic and Criminal codes in the corpus answer their questions, 0.89-0.96, just like the Convention questions that
    Jev misjudges); it only becomes the confidence of an accepted question.
    """
    if settings.GATE_JEV_SCOPE_ENABLED and in_scope is not None and in_scope < settings.GATE_JEV_MIN_IN_SCOPE:
        return GateDecision(False, "jev_out_of_scope", in_scope)
    return GateDecision(True, "jev_match", answerable if answerable is not None else (top_probability or 1.0))
