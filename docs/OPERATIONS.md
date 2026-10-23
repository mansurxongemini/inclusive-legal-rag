# Operations guide

How the service is run, what it costs, how it degrades, and how to check that a change did not make it worse.

## Providers and cost

| Role | Provider | Model | Cost driver |
|---|---|---|---|
| Answer generation, query rewriting/translation, history condensing, claim check, evaluation judge | Meta AI (`OPENROUTER_BASE_URL`) | `muse-spark-1.3` (judge: `muse-spark-1.2`), reasoning effort `minimal` for light calls | prepaid Meta credit; the second key `PLUS_META_AI_API_KEY` is used after the first answers HTTP 402 |
| Embeddings | OpenRouter | `baai/bge-m3` | negligible (about $0.0000001 per question) |
| Reranking + scope gate | Meta AI by default (`src/retrieval/llm_ranker.py`); OpenRouter `typesafe/jev-1.13` only when `JEV_ENABLED=true` | `muse-spark-1.3` at minimal reasoning | Jev is the only real OpenRouter cost: about $0.0006 per question |

**OpenRouter serves embeddings and, optionally, Jev** (owner's decision, 2026-10-23: the balance is small, so Jev is off by default and Meta ranks); there is no chat model on OpenRouter. If the Meta
keys are both out of credit the answer is the sources-only fallback (the quoted norms with citations).

**Budget guard** (`src/clients/spend.py`). Every OpenRouter response carries `usage.cost`; the ledger (`data/store/spend.db`)
sums it per month. `OPENROUTER_MONTHLY_BUDGET_USD` (default 15) has two thresholds:

- 80% (`OPENROUTER_BUDGET_SOFT_RATIO`): `/health` reports `soft` (a warning; nothing is switched off yet).
- 100%: embeddings and Jev pause too; retrieval is full-text search with the RRF order until the month changes.
  `/health` reports `openrouter_budget: ok | soft | exhausted`.

Measured cost per question is about $0.00036 (retrieval) with no cache hit, so 30 000 uncached questions a month cost
about $11. Cache hits cost nothing. Evaluation scripts count into their own ledger (`spend_eval.db`) and are not limited.

## Retrieval modes and what they cost (stress dev split, 59 questions; intervals are about +/-12 points)

| Mode | Switches | OpenRouter cost per question | Expected unit first / in top 6 | Out-of-scope refused |
|---|---|---|---|---|
| Jev + vectors | `JEV_ENABLED=true` | about $0.0006 | 81% / 96% | 100% |
| **Vectors + Meta ranker (default)** | `JEV_ENABLED=false` | about $0.000001 (embeddings only) | 62% / 91% | 100% |
| OpenRouter paused: full-text + Meta ranker | `OPENROUTER_PAUSED=true` | 0 | 70% / 87% | 100% |
| OpenRouter paused, no ranker (RRF order) | `OPENROUTER_PAUSED=true LLM_RANK_FALLBACK=false` | 0 | 32% / 68% | 50% |

The Meta ranker shows 30 candidates x 1200 characters (`LLM_RANK_UNITS`, `LLM_RANK_CHARS`); a smaller window (20 x 700) gave 51% first / 77% top 6.
Meta's scope judge is decisive (0.0 for out-of-scope questions): on the stress set 100% of out-of-scope questions are refused with 2.3% of
in-scope ones refused wrongly, on the held-out set 95% / 7.3% (Jev: 100% / 1.2% and 95% / 3.6%).

`OPENROUTER_PAUSED=true` stops every OpenRouter call at once; the service also pauses itself when the balance read from OpenRouter
(`GET /key`, `GET /credits`, every 15 minutes) is at or below `OPENROUTER_RESERVE_USD` (0.05).

## Degradation, in order

1. First Meta key answers 402 -> second key. 2. (Optional) `GENERATION_MODEL_BACKUP`, empty by default.
3. Both Meta keys fail -> **sources-only answer**: the text of the best matching norms with citations (`degraded: true`, not cached).
4. Jev unavailable, paused or switched off -> the Meta ranker (RRF order and the older relevance gate only if that fails too). 5. Embeddings unavailable or paused -> full-text only.
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
       --judge-model muse-spark-1.2 --baseline <old report>           # end to end: answers + judge + deterministic checks
.venv/bin/python scripts/profile_retrieval.py --limit 12                          # where retrieval time goes
.venv/bin/python scripts/diagnose_question.py s075                                # why one question misses its unit
.venv/bin/python scripts/calibrate_scope.py --dataset data/golden_dataset/heldout_v1.json   # scope gate separation
```

`data/golden_dataset/heldout_v1.json` (55 in-scope and 40 out-of-scope questions written from sampled units that no other
set uses) is a held-out set: do not tune on it. Its sha256 is in `heldout_v1.manifest.json`.

Evaluation judges run on Meta too (`--judge-model muse-spark-1.2`, a different model version from the generator). Check the OpenRouter
key first (`GET /api/v1/key`, field `limit_remaining`): a retrieval-only benchmark of 200 questions costs about $0.12 of Jev.

## Security notes

- Administration needs `ADMIN_API_KEY`; the loopback shortcut is off by default as soon as a key is configured.
- Public question endpoints: 256 KB body limit, per-IP rate limit (the real address behind nginx via uvicorn `--proxy-headers`),
  daily cap on generated answers, security headers and a CSP.
- Rotate any key that was ever printed in logs or committed: the gateway key in commit `13001dc` (scripts/eval_3way_sample.py,
  not pushed), the GitHub token inside the `origin` URL, and the Tuzuk JWT in the public history (`ea3093c`).
