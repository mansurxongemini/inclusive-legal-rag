# Embedding model comparison: bge-m3 vs qwen3-embedding-8b (2026-10-25)

Asked by the owner ("why not multilingual-e5-large or a legal embedding model?"). Measured on a copy of the store; the
owner then approved the switch ("if it really is better"), it was measured again on the current data, and production
uses **qwen/qwen3-embedding-8b** at 1024 dimensions since 2026-10-25.

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

- Re-embedding the store: about 11 minutes, about $0.17 measured on the balance (same price per token as bge-m3).
- Per question: unchanged ($0.01 / M tokens for the question embedding).
- Storage and RAM: unchanged at 1024 dimensions.

## Second measurement before the switch (current data, 2026-10-25)

Same corpus as cycle 13 (28 667 units), every unit re-embedded with qwen3 in a copy:

| | bge-m3 (cycle 13) | qwen3-embedding-8b |
|---|---|---|
| dense only: recall@5 / MRR@20 | 0.707 / 0.539 | **0.807 / 0.698** |
| whole path: recall@5 / MRR | 0.964 / 0.921 | **0.971 / 0.971** |
| citations, refusals, language, key facts, traps | 100% each | 100% each |

Thresholds that depend on the model's scores were checked for qwen3 before the switch:

- **Semantic answer cache** (`SEMANTIC_CACHE_THRESHOLD` 0.95, `eval/calibrate_semantic_cache.py`): the most similar pair of
  *different* questions scores 0.895 with qwen3 (0.912 with bge-m3), so no wrong cached answer; 3 of 10 rephrasings are
  reused, as before. The threshold stays.
- **Relevance gate, dense branch** (`GATE_MIN_VECTOR_SCORE` 0.82, `eval/dense_only.py`, used only when the ranking model
  is unavailable): 62 of 70 in-corpus questions pass (bge-m3: 63) and 1 of 6 out-of-corpus ones (bge-m3: 2). Stays.
- **Translation audit** (`scripts/audit_translations.py`): its thresholds are bge-m3 scores, so the audit keeps bge-m3
  (fixed in the script) instead of following the service's model.

## How the switch is made (and how to switch again)

```bash
scripts/backup.sh --keep 14                       # verified backup first; stop the server
# EMBEDDING_MODEL / EMBEDDING_REQUEST_DIMENSIONS in .env or src/config.py
python scripts/reembed_context.py --all --batch-size 40 --concurrency 6     # ~11 min, ~$0.17, resumable
python eval/run_eval.py --label "<model> in production"
```

The store records the model of its vectors (`data/store/embedding_model.json`). The re-embedding writes it only when every
unit has new vectors; a server whose configured model differs from it searches full text only (and `/health` reports
`degraded`), and indexing refuses to add vectors of another model, so the two models are never mixed. The answer cache is
keyed by the embedding model too, so no answer or question vector of the old model is reused.
