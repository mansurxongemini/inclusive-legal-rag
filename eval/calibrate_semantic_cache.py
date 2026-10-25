#!/usr/bin/env python3
"""
Calibrates SEMANTIC_CACHE_THRESHOLD (src/gateway/service.py) for the configured embedding model.

A semantic-cache hit serves a stored answer for a rephrased question, so the threshold must sit above the similarity of
every pair of DIFFERENT questions (gold-set questions with different expected units, plus near misses written here:
annual vs unpaid leave, pension vs allowance, dismissal vs hiring) and, to be useful, below rephrasings of one question.
Run it after changing EMBEDDING_MODEL; it embeds about 200 short questions (well under $0.001).

  python eval/calibrate_semantic_cache.py
  EMBEDDING_MODEL=baai/bge-m3 EMBEDDING_REQUEST_DIMENSIONS=0 python eval/calibrate_semantic_cache.py
"""
import asyncio
import itertools
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SPEND_SCOPE", "eval")

from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.config import settings  # noqa: E402
from src.gateway.service import SEMANTIC_CACHE_THRESHOLD  # noqa: E402

# the same question in other words: a hit is wanted (an answer reused)
SAME = [
    ("I guruh nogironligi bo'lgan xodim haftasiga necha soat ishlaydi?",
     "I guruh nogironligi bo'lgan ishchining haftalik ish vaqti qancha?"),
    ("Nogironlik nafaqasi qanday tayinlanadi?", "Nogironlik nafaqasini tayinlash tartibi qanday?"),
    ("TIEK qayerda o'tkaziladi?", "Tibbiy-ijtimoiy ekspert komissiyasi qayerda o'tkaziladi?"),
    ("Nogironligi bo'lgan bola tarbiyalayotgan onaga qanday imtiyozlar bor?",
     "Nogiron bolasini tarbiyalayotgan onaga qanday imtiyozlar beriladi?"),
    ("Сколько дней ежегодного отпуска положено работнику с инвалидностью II группы?",
     "Какой ежегодный отпуск у работника с инвалидностью II группы?"),
    ("Как назначается пособие по инвалидности?", "Каков порядок назначения пособия по инвалидности?"),
    ("Положена ли человеку с инвалидностью бесплатная инвалидная коляска?",
     "Может ли человек с инвалидностью получить инвалидную коляску бесплатно?"),
    ("How many hours a week does an employee with a Group I disability work?",
     "What are the weekly working hours of an employee with a Group I disability?"),
    ("How is a disability allowance granted?", "What is the procedure for granting a disability allowance?"),
    ("Can a person with a disability get a free wheelchair?",
     "Is a wheelchair given free of charge to a person with a disability?"),
]
# different questions that look alike: a hit would serve a wrong answer
DIFFERENT = [
    ("Nogironligi bo'lgan xodimga yillik ta'til necha kun?",
     "Nogironligi bo'lgan xodimga haq to'lanmaydigan ta'til necha kun?"),
    ("Nogironlik pensiyasi qanday hisoblanadi?", "Nogironlik nafaqasi qanday hisoblanadi?"),
    ("Nogironligi bo'lgan xodimni ishdan bo'shatish mumkinmi?",
     "Nogironligi bo'lgan shaxsni ishga olishni rad etish mumkinmi?"),
    ("Nogironligi bo'lgan bolaga nafaqa qancha?", "Nogironligi bo'lgan bolaga pensiya qancha?"),
    ("Какой отпуск положен работнику с инвалидностью?", "Какая пенсия положена работнику с инвалидностью?"),
    ("Можно ли уволить работника с инвалидностью?", "Можно ли отказать в приёме на работу человеку с инвалидностью?"),
    ("Кто проводит медико-социальную экспертизу?", "Как обжаловать решение медико-социальной экспертизы?"),
    ("Can an employer dismiss a worker with a disability?",
     "Can an employer refuse to hire a person with a disability?"),
    ("How long is the annual leave of an employee with a disability?",
     "How long is the unpaid leave of an employee with a disability?"),
    ("Who conducts the medical and social examination?", "How do I appeal a medical and social examination decision?"),
]


def gold_pairs():
    """Pairs of gold questions in one language whose expected units do not overlap (different answers)."""
    items = [json.loads(line) for line in open(ROOT / "eval" / "gold_set.jsonl", encoding="utf-8")]
    items = [i for i in items if i.get("expected")]
    for a, b in itertools.combinations(items, 2):
        ids_a = {c for slot in a["expected"] for c in slot}
        ids_b = {c for slot in b["expected"] for c in slot}
        if a["language"] == b["language"] and not ids_a & ids_b:
            yield a["question"], b["question"]


async def main() -> int:
    client = OpenRouterClient()
    pairs = {"same": SAME, "different": DIFFERENT, "gold_different": list(gold_pairs())}
    texts = sorted({t for group in pairs.values() for pair in group for t in pair})
    vecs = {}
    for i in range(0, len(texts), 64):
        part = texts[i:i + 64]
        for t, v in zip(part, await client.get_query_embeddings(part)):
            v = np.asarray(v, dtype=np.float32)
            vecs[t] = v / (np.linalg.norm(v) or 1.0)
    await client.close()
    sims = {k: sorted(float(vecs[a] @ vecs[b]) for a, b in group) for k, group in pairs.items()}
    hi_diff = max(sims["different"][-1], sims["gold_different"][-1])
    lo_same = sims["same"][0]
    print(f"model {settings.EMBEDDING_MODEL} (dimensions {settings.EMBEDDING_REQUEST_DIMENSIONS or 'native'})")
    for k, s in sims.items():
        print(f"  {k:15s} n={len(s):4d}  min {s[0]:.3f}  median {s[len(s) // 2]:.3f}  max {s[-1]:.3f}")
    reused = sum(s >= SEMANTIC_CACHE_THRESHOLD for s in sims["same"])
    wrong = sum(s >= SEMANTIC_CACHE_THRESHOLD for s in sims["different"] + sims["gold_different"])
    print(f"threshold {SEMANTIC_CACHE_THRESHOLD}: {wrong} different-question pairs would hit (must be 0), "
          f"{reused}/{len(sims['same'])} rephrasings reused; highest different pair {hi_diff:.3f}, lowest rephrasing {lo_same:.3f}")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
