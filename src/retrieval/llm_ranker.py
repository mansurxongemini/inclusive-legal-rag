"""
Reranking and scope check on the generation provider (Meta AI), used when Jev (OpenRouter) is unavailable: the key's
balance is at its reserve, OPENROUTER_PAUSED is on, or the provider refused. It answers the same two questions as Jev --
which passages answer the question, and is the question in scope -- with one small chat call each, so that retrieval
keeps a judged order instead of falling back to the plain rank-fusion order and a gate without a scope signal.
"""
import json
import logging
import re
from typing import List, Optional

from src.config import settings
from src.retrieval.passages import focused_text

logger = logging.getLogger(__name__)

# probability given to the 1st, 2nd, ... passage of the model's list (the same scale as Jev's "best" choice)
RANK_PROBABILITIES = [0.50, 0.20, 0.10, 0.06, 0.04, 0.03, 0.02, 0.015]
OTHER_PROBABILITY = 0.001

RANK_SYSTEM = (
    "You are the retrieval judge of a legal assistant for persons with disabilities in Uzbekistan. You get a QUESTION and "
    "numbered PASSAGES (provisions of Uzbek legislation). Pick the passages that directly answer the question: they contain "
    "the rule, number, deadline or condition that is asked about. Prefer a provision in force over a proposal or a plan. "
    "If the question has several parts, include the best passage for each part. Reply with ONLY a JSON object: "
    '{"best": [passage numbers, most useful first, at most 8], "answerable": a number from 0 to 1 = the probability that the '
    "passages contain the answer}."
)
SCOPE_SYSTEM = (
    "The text is a question sent to the legal assistant of Huquq+, a rights-protection service for persons with disabilities "
    "and their families in Uzbekistan. It answers from Uzbekistan's legislation about the asker's own rights and how to "
    "defend them. IN SCOPE: {in_scope}. OUT OF SCOPE (other law): {other_law}. Also out of scope: {not_legal}; "
    "{manipulation}. Reply with ONLY a JSON object: "
    '{{"in_scope": a number from 0 to 1 = the probability that the question is in scope}}.'
)


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def _probability(value) -> Optional[float]:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return None


class LlmRanker:
    def __init__(self, client):
        self.client = client

    async def _ask(self, system: str, user: str, max_tokens: int = 600) -> dict:
        raw = await self.client.chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0, max_tokens=max_tokens, min_chars=2, reasoning={"enabled": False}, light=True,
        )
        return _json(raw)

    async def scope(self, question: str) -> Optional[float]:
        from src.retrieval.jev_ranker import SCOPE_QUESTION
        try:
            data = await self._ask(SCOPE_SYSTEM.format(**SCOPE_QUESTION["criteria"]), question, max_tokens=200)
        except Exception as e:
            logger.warning(f"Fallback scope check failed: {e}")
            return None
        p = _probability(data.get("in_scope"))
        return None if p is None else min(1.0, p * settings.LLM_SCOPE_SCALE)

    async def rank(self, query: str, contexts: list, subquestions: Optional[List[str]] = None):
        """JevRankResult over `contexts` (all of them keep their place; the model's picks come first), or None."""
        from src.retrieval.jev_ranker import JevRankResult
        if not contexts:
            return None
        window = contexts[:settings.LLM_RANK_UNITS]
        passages = []
        for n, ctx in enumerate(window):
            meta = ctx.article.metadata
            title = (meta.law_title or {}).get("uz", "")
            text = focused_text(ctx.article, "uz", getattr(ctx, "focus", None), settings.LLM_RANK_CHARS)
            passages.append(f"[{n + 1}] {title} {meta.article_number}. {text}")
        parts = ""
        if subquestions:
            parts = "\nThe question has these parts:\n" + "\n".join(f"- {q}" for q in subquestions) + "\n"
        try:
            data = await self._ask(RANK_SYSTEM, f"QUESTION: {query}\n{parts}\nPASSAGES:\n" + "\n\n".join(passages))
        except Exception as e:
            logger.warning(f"Fallback rerank failed: {e}")
            return None
        picks: List[int] = []
        for v in data.get("best") or []:
            try:
                i = int(v) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(window) and i not in picks:
                picks.append(i)
        if not picks:
            if "best" not in data:
                return None                      # not an answer to the question at all
            # "no passage answers it" is a judgement too (an out-of-scope or unanswerable question): keep the order, mark
            # every passage as unlikely and trust the answerable value
            answerable = _probability(data.get("answerable"))
            return JevRankResult(order=list(range(len(contexts))), probabilities=[OTHER_PROBABILITY] * len(contexts),
                                 answerable=0.0 if answerable is None else min(answerable, 0.2))
        probabilities = [OTHER_PROBABILITY] * len(contexts)
        for rank, i in enumerate(picks[:len(RANK_PROBABILITIES)]):
            probabilities[i] = RANK_PROBABILITIES[rank]
        order = picks + [i for i in range(len(contexts)) if i not in picks]
        return JevRankResult(order=order, probabilities=probabilities, answerable=_probability(data.get("answerable")))
