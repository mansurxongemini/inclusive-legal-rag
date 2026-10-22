# Operations guide

How the service is run, what it costs, how it degrades, and how to check that a change did not make it worse.

## Providers and cost

| Role | Provider | Model | Cost driver |
|---|---|---|---|
| Answer generation | Meta AI (`OPENROUTER_BASE_URL`) | `muse-spark-1.3`, reasoning effort `minimal` | prepaid Meta credit; the second key `PLUS_META_AI_API_KEY` is used after the first answers HTTP 402 |
| Embeddings | OpenRouter | `baai/bge-m3` | negligible (about $0.0000001 per question) |
| Reranking + scope gate | OpenRouter | `typesafe/jev-1.13` | the main OpenRouter cost: about $0.00025 per question (30 units x 1500 characters) |
| Light calls (query rewrite/translation, claim check), backup generation, evaluation judge | OpenRouter | **one model**: `anthropic/claude-haiku-5.5` | about $0.0001 per question; backup answers about $0.001 each |

**Budget guard** (`src/clients/spend.py`). Every OpenRouter response carries `usage.cost`; the ledger (`data/store/spend.db`)
sums it per month. `OPENROUTER_MONTHLY_BUDGET_USD` (default 15) has two thresholds:

- 80% (`OPENROUTER_BUDGET_SOFT_RATIO`): the light calls stop using OpenRouter and run on the generation provider instead;
  the backup model is not used.
- 100%: embeddings and Jev pause too; retrieval is full-text search with the RRF order until the month changes.
  `/health` reports `openrouter_budget: ok | soft | exhausted`.

Measured cost per question is about $0.00036 (retrieval) with no cache hit, so 30 000 uncached questions a month cost
about $11. Cache hits cost nothing. Evaluation scripts count into their own ledger (`spend_eval.db`) and are not limited.

## Degradation, in order

1. First Meta key answers 402 -> second key. 2. Generation model fails -> `GENERATION_MODEL_BACKUP` (Haiku, OpenRouter).
3. Both fail -> **sources-only answer**: the text of the best matching norms with citations (`degraded: true`, not cached).
4. Jev unavailable or paused -> RRF order and the older relevance gate. 5. Embeddings unavailable or paused -> full-text only.
6. `PUBLIC_DAILY_GENERATIONS` reached -> HTTP 429 / stream error event with an explanation.

## Memory

Idle about 180 MB; a vector search reads the whole 56 000 x 1024 table. glibc's default allocator kept those buffers
and the resident memory grew to 900+ MB. `src/runtime_tuning.py` (called when the app starts) and the environment in
`legal-rag.service` / the Dockerfile (`MALLOC_ARENA_MAX=2`, `MALLOC_MMAP_THRESHOLD_=65536`) keep it near 200 MB.

## Backup and restore

```bash
scripts/backup.sh --keep 14            # data/backups/legal_rag_backup_<time>/ : SQLite online backup + verified LanceDB copy
scripts/restore.sh <backup folder>     # server must be stopped; the current store is moved to data/backups/pre_restore_<time>/
```

## Checking a change

```bash
.venv/bin/python -m pytest -q                                                    # about 50 s, no network
.venv/bin/python scripts/stress_eval.py --retrieval-only --baseline <old report>  # exit code 1 on a regression > 3 points
.venv/bin/python scripts/stress_eval.py --only @data/golden_dataset/stress_dev_split.json --profile prod \
       --judge-model anthropic/claude-haiku-5.5 --baseline <old report>           # end to end: answers + judge + deterministic checks
.venv/bin/python scripts/profile_retrieval.py --limit 12                          # where retrieval time goes
.venv/bin/python scripts/diagnose_question.py s075                                # why one question misses its unit
.venv/bin/python scripts/calibrate_scope.py --dataset data/golden_dataset/heldout_v1.json   # scope gate separation
```

`data/golden_dataset/heldout_v1.json` (55 in-scope and 40 out-of-scope questions written from sampled units that no other
set uses) is a held-out set: do not tune on it. Its sha256 is in `heldout_v1.manifest.json`.

Evaluation judges: use the same single OpenRouter model (`--judge-model anthropic/claude-haiku-5.5`, about $0.001 per
judged answer). An independent judge from another vendor is better evidence but costs 20 times more.

## Security notes

- Administration needs `ADMIN_API_KEY`; the loopback shortcut is off by default as soon as a key is configured.
- Public question endpoints: 256 KB body limit, per-IP rate limit (the real address behind nginx via uvicorn `--proxy-headers`),
  daily cap on generated answers, security headers and a CSP.
- Rotate any key that was ever printed in logs or committed: the gateway key in commit `13001dc` (scripts/eval_3way_sample.py,
  not pushed), the GitHub token inside the `origin` URL, and the Tuzuk JWT in the public history (`ea3093c`).
