# Embedding model comparison: bge-m3 vs qwen3-embedding-8b (2026-10-25)

Asked by the owner ("why not multilingual-e5-large or a legal embedding model?"). Measured on a copy of the store; the
production model was **not** changed (owner's rule: switch only after asking).

## Candidates on OpenRouter (prices of 2026-10-25)

| Model | Price | Context | Notes |
|---|---|---|---|
| baai/bge-m3 (production) | $0.01 / M tokens | 8 194 tokens | multilingual (Uzbek included), 1024 dimensions |
| intfloat/multilingual-e5-large | $0.01 / M | **512 tokens** | 3 704 of 28 667 units (13%) are longer than ~512 tokens; older |
| legal models (voyage-law-2, Legal-BERT) | not on OpenRouter | - | trained on English (US/EU) law; would need a second provider and key |
| qwen/qwen3-embedding-8b | $0.01 / M | 40 960 tokens | multilingual, adjustable size (`dimensions`), newer |

multilingual-e5-large was not measured: its 512-token limit and the published comparisons by the BGE-M3 authors make
it weaker than bge-m3 for long statutory units. qwen3-embedding-8b was the one worth measuring.

## Method

1. A consistent copy of the store (`scripts/backup_store.py --dest ...`), all 28 667 units re-embedded with
   `EMBEDDING_MODEL=qwen/qwen3-embedding-8b EMBEDDING_REQUEST_DIMENSIONS=1024` (same 1024-wide table, 520 s).
2. `eval/dense_only.py`: the 70 gold questions with expected units, vector search alone (no full-text search, no ranker).
3. `eval/run_eval.py`: the whole production path (full-text + vectors + model ranker + generation) on the copy.

## Results

Dense retrieval alone (70 questions):

| | bge-m3 | qwen3, no instruction | qwen3, with a query instruction |
|---|---|---|---|
| recall@5 | 0.707 | **0.836** | 0.764 |
| recall@20 | 0.900 | **0.943** | 0.914 |
| MRR@20 | 0.539 | **0.696** | 0.628 |
| recall@5 uz / ru / en | 0.688 / 0.674 / 0.761 | 0.771 / 0.913 / 0.826 | 0.750 / 0.761 / 0.783 |

The English task instruction that Qwen recommends made it worse here: use it without one (`EMBEDDING_QUERY_INSTRUCTION=""`).

Whole production path (76 questions; bge-m3 = regression cycle 8 on the same data):

| | bge-m3 | qwen3-embedding-8b |
|---|---|---|
| recall@5 | 0.964 | **0.971** |
| MRR | 0.921 | **0.957** |
| valid citations, honest refusals, language, key facts, repealed-act traps | 100% each | 100% each |
| invented numbers | 0 | 0 (one "7.5 hours" from "7 soat 30 daqiqa" was a checker false positive, fixed) |

The model ranker and full-text search already make up for most of bge-m3's weaker vectors, so the end-to-end gain is
smaller than the dense one: +0.7 points of recall@5, +3.6 points of MRR (the right unit ranked higher). Russian and
English questions gain most from the better vectors.

## Cost of a switch

- Re-embedding the store: about 9 minutes, about $0.08 (same price per token as bge-m3).
- Per question: unchanged ($0.01 / M tokens for the question embedding).
- Storage and RAM: unchanged at 1024 dimensions.

## How to switch (after the owner's decision)

```bash
scripts/backup.sh --keep 14                                              # verified backup first
# .env
EMBEDDING_MODEL=qwen/qwen3-embedding-8b
EMBEDDING_REQUEST_DIMENSIONS=1024
# re-embed every unit (the server must be stopped; vectors of the old model must not be mixed with the new ones)
python - <<'EOF'
import asyncio
from src.clients.openrouter import OpenRouterClient
from src.storage.hybrid_store import HybridStore
async def main():
    store, client = HybridStore(), OpenRouterClient()
    with store.fts_store._get_connection() as conn:
        ids = [r[0] for r in conn.execute("SELECT canonical_id FROM articles_metadata")]
    arts = list(store.get_articles_batch(ids).values())
    print(await store.reembed_articles(arts, client=client, batch_size=40, concurrency=6))
    await client.close()
asyncio.run(main())
EOF
python eval/run_eval.py --label "qwen3 in production"                     # expect recall@5 >= 0.96, MRR >= 0.95
```

Also bump `ANSWER_VERSION` in `src/generation/prompts.py`: the semantic answer cache holds bge-m3 question vectors.
