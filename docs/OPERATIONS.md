# Operations guide

How the service is run, what it costs, how it degrades, and how to check that a change did not make it worse.

## Providers and cost

One OpenRouter key (`OPENROUTER_API_KEY`) and one endpoint (`OPENROUTER_BASE_URL`) serve every call; Meta AI was only a test provider and
is gone from the code (no second key, no side endpoints, no backup or fallback model).

| Role | Model | Setting |
|---|---|---|
| Answer generation, query rewriting, translation, history condensing, ranking and scope check, claim check, review | **one chat model**, `deepseek/deepseek-v4-flash-0731` | `GENERATION_MODEL_PRIMARY` (OpenRouter falls back between the providers of that model) |
| Embeddings | `baai/bge-m3` | `EMBEDDING_MODEL` |
| Reranking + scope gate, optional | `typesafe/jev-1.13` | `JEV_ENABLED=true` (off by default) |

A `.env` that still holds the old Meta settings (`PLUS_META_AI_API_KEY`, `EMBEDDING_*`, `JEV_BASE_URL`/`JEV_API_KEY`, `UTILITY_*`,
`GENERATION_MODEL_BACKUP`/`_FALLBACK`, `WORKERS`) is reported in the log at start-up: they are no longer read. **`OPENROUTER_API_KEY` must be an
OpenRouter key and `OPENROUTER_BASE_URL` must be `https://openrouter.ai/api/v1`**, and `GENERATION_MODEL_PRIMARY` an OpenRouter model name.

**Default chat model: `deepseek/deepseek-v4-flash-0731`** (OpenRouter's list, 2026-10-24: 1M context, supports `reasoning` and `response_format`, 20+ providers).
`LLM_PROVIDER_ORDER=deepinfra` asks DeepInfra first (fp8, $0.06 per million input and $0.18 per million output tokens; the cheapest provider, Baidu, asks
$0.044 / $0.133 and the fp4 ones are excluded by `LLM_PROVIDER_QUANTIZATIONS`). Not yet tried with a real key: send one question and read the answer and
`/health/details` -> `spend` before relying on it (the reasoning switch `GENERATION_REASONING_EFFORT=none` is expected to turn its thinking off).

**What an uncached question costs** (token counts estimated from the prompt sizes, prices from the list above): about 6-7k input tokens for the
answer, about 12k for the chat-model ranker (30 units x 1200 characters, `LLM_RANK_UNITS` / `LLM_RANK_CHARS`), under 1k for the scope check and each
helper call, about 0.4k output tokens: roughly 20k input tokens, **about $0.0013 per question**. That is about 11 000 uncached questions for the
default budget of 15 USD (about 370 a day). At 1 000 questions a day with half of them answered from the cache the month costs about 20 USD:
raise `OPENROUTER_MONTHLY_BUDGET_USD`, or shrink the ranker window (20 x 700 halves its share and costs accuracy, see below).
`/health/details` -> `spend.by_kind` shows the real figures (`chat`, `embedding`, `jev`): calibrate on them. Cache hits cost nothing.

**Budget guard** (`src/clients/spend.py`). Every OpenRouter response carries `usage.cost` (a stream carries it in its last chunk); the ledger
(`data/store/spend.db`) sums it per month. `OPENROUTER_MONTHLY_BUDGET_USD` (default 15) has two thresholds:

- 80% (`OPENROUTER_BUDGET_SOFT_RATIO`): the optional calls stop (query rewrites, claim check, history condensing); the answer itself, the
  translation of a Russian or English question and the ranking still run.
- 100%: no call at all. Retrieval is full-text search with the RRF order, and an answer is the quoted text of the best matching norms with
  citations (`degraded: true`, no model writes a word of it) until the month changes or the key is topped up.

`/health/details` (administrators only; the public `/health` shows just the status) reports `openrouter_budget: ok | soft | exhausted` and the spend.
Evaluation scripts count into their own ledger (`spend_eval.db`) and are not limited.

`OPENROUTER_PAUSED=true` stops every call at once; the service also pauses itself when the key's balance (`GET /key`, `GET /credits`, read every
15 minutes) is at or below `OPENROUTER_RESERVE_USD` (0.05), and for 15 minutes after the provider answers 402 or a limit error.

## Retrieval modes (stress dev split, 59 questions; intervals are about +/-12 points)

| Mode | Switches | Expected unit first / in top 6 | Out-of-scope refused |
|---|---|---|---|
| Jev + vectors | `JEV_ENABLED=true` | 81% / 96% | 100% |
| **Vectors + chat-model ranker (default)** | `JEV_ENABLED=false` | 62% / 91% | 100% |
| No model (budget used up or paused): RRF order | `OPENROUTER_PAUSED=true` | 32% / 68% | 50% |

These figures were measured with `muse-spark-1.3` as the ranker: **measure again after choosing the production chat model**
(`scripts/stress_eval.py`, see "Checking a change"). A smaller ranker window (20 x 700) gave 51% first / 77% top 6.
The scope judge is decisive (0.0 for out-of-scope questions): on the stress set 100% of out-of-scope questions were refused with 2.3% of
in-scope ones refused wrongly, on the held-out set 95% / 7.3% (Jev: 100% / 1.2% and 95% / 3.6%).

## Degradation, in order

1. The chat model does not answer (after one more try) or the budget is used up -> **sources-only answer**: the text of the best matching norms
   with citations (`degraded: true`, not cached). 2. Jev unavailable or switched off -> the chat-model ranker (RRF order and the older relevance gate
   only if that fails too). 3. Embeddings unavailable or paused -> full-text only.
4. `PUBLIC_DAILY_GENERATIONS` reached -> HTTP 429 / stream error event with an explanation.

## Memory

Idle about 180 MB, about 230 MB after a day of questions. Two things used to push the process to 900-1300 MB:

1. A vector search reads the whole table in large Arrow buffers; glibc's default allocator kept them. `src/runtime_tuning.py` (called when the
   app starts) and the environment in `legal-rag.service` / the Dockerfile (`MALLOC_ARENA_MAX=2`, `MALLOC_MMAP_THRESHOLD_=65536`) return them.
2. **The hourly Huquq+ sync** built its link index by parsing all 28 000 units with their full texts (`list_articles(limit=100000)`) and left the
   process 600 MB heavier for good (152 -> 777 MB measured). It now reads only the metadata fields it needs with SQLite `json_extract`
   (`SqliteFtsStore.iter_link_metadata`; 152 -> 223 MB, the index is identical).

Do not call `list_articles()` with a large limit in a serving process.

## Language policy

- **Questions and answers: Uzbek (Latin or Cyrillic), Russian, English.** The language is detected from the question (`QueryAnalyzer`, which
  falls back to Uzbek when there is no evidence either way; `language` = `auto|uz|ru|en` overrides it) and the whole answer is written in it: the
  text, the disclaimer, the refusal, the source heading, the error message. An Uzbek answer follows the script of the question.
- **Search is Uzbek only** (`VECTOR_LANGUAGES=uz`): every vector is of an Uzbek text. A Russian or English question is translated to Uzbek
  (`QueryTranslator.to_uzbek`) and searched there, together with its own words for the vector search; an Uzbek question gets a standard-Latin rewrite.
- **Review** (`POST /api/v1/assistant/review`): `summary`, `problem`, `fix` and `delivery_hint` are written in the language of the citizen's question
  (`language` = `auto|uz|oz|ru|en`; `oz` = Uzbek in Cyrillic) and the response says which one in `language`.
- **Huquq+**: only the Uzbek posts are synchronized (`HUQUQPLUS_LANGUAGES=uz`). The Russian version of a post says what the Uzbek one says and a unit without
  Uzbek text has no vector and no full-text row, so it could never be found. The posts of another language that were stored earlier are removed on the next
  full sync (`purge_disallowed_languages`: units, links, answer cache; 88 posts / 257 units on 2026-10-24).

## Settings

`.env.example` lists only what a deployment has to set. **Every setting, with a comment, is in `src/config.py`** and has a working default; set one in
`.env` only to change it. The ones worth knowing:

| Setting | Default | What it does |
|---|---|---|
| `JEV_ENABLED` | false | rank with Jev instead of the chat model (better, costs more) |
| `OPENROUTER_PAUSED` | false | stop every paid call at once |
| `PUBLIC_DAILY_GENERATIONS` | 3000 | answers generated a day (cache hits are free); 0 = no cap |
| `RATE_LIMIT_PER_MINUTE`, `PUBLIC_BROWSE_RATE_PER_MINUTE`, `FEEDBACK_RATE_PER_MINUTE` | 60, 30, 6 | per visitor address |
| `VECTOR_LANGUAGES`, `HUQUQPLUS_LANGUAGES` | uz, uz | languages that get vectors / that are synchronized from Huquq+ |
| `SUPPORT_CHECK_ENABLED` | false | claim check (measured, see the last section) |
| `STORAGE_DIR`, `CACHE_DB_PATH` | `./data/store`, `./data/cache/query_cache.db` | where the data lives (Docker sets them) |
| `LOG_LEVEL` | INFO | |
| `MOCK_EXTERNAL_APIS` | false | offline placeholder answers (also the mode without a key) |

## Public endpoints and their limits

| Endpoint | Protection |
|---|---|
| `POST /api/v1/query` | `RATE_LIMIT_PER_MINUTE` per visitor address, `MAX_PUBLIC_BODY_BYTES`, `PUBLIC_DAILY_GENERATIONS` |
| `GET /api/v1/article/{id}`, `GET /api/v1/inclusive/norms`, `/documents`, `/documents/{law}/norms`, `/stats` | `PUBLIC_BROWSE_RATE_PER_MINUTE` per address, in its own budget (asking is not browsing); the administrator is not limited |
| `GET /api/v1/articles` (pages through all texts) | administrators only |
| `POST /api/v1/feedback` | `FEEDBACK_RATE_PER_MINUTE` per address |
| `GET /health` | public, status only; `GET /health/details` (memory, budget state, corpus size) is administrative |

The address is the TCP peer, or, with `TRUSTED_PROXIES=N`, the Nth entry from the right of `X-Forwarded-For`. Behind nginx set
`TRUSTED_PROXIES=1`; without it every visitor shares the proxy's address and one budget. Do not combine it with uvicorn's
`--proxy-headers --forwarded-allow-ips` (the systemd unit uses that instead). The limiter keeps its state in memory, so
the service runs with one worker; the daily generation cap and the limits restart with the process.

The answer cache (`CACHE_DB_PATH`) drops entries older than `CACHE_TTL_SECONDS` once a day.

## Docker

```bash
cp .env.example .env          # the settings you must fill in; compose keeps no copy of them (the rest default in src/config.py)
podman compose up -d --build  # or docker compose
```

The image installs the exact versions of `requirements.lock`. The CI workflow (`.github/workflows/ci.yml`) runs `pyflakes`, the
tests and a Docker build on every push.

## Russian texts

The Russian texts of 15 504 units are kept in the store (a unit without Uzbek text is still shown to the model in Russian), but they are **not searched**
(`VECTOR_LANGUAGES=uz` - the only language that gets vectors, in code: `vector_languages()`; `FTS_EXCLUDE_LANGUAGES=ru`): a Russian question is translated to Uzbek and searched there. Measured on 22 Russian
questions, two runs per arm, hit@6: 77% with the Russian texts searched, 82% without their vectors, 86% without vectors and full-text rows; on the
59-question dev split (Uzbek and Russian) 91% -> 92-94%. The Russian vector rows (20 402) and full-text rows (17 018) were deleted on 2026-10-23, which
shrank the vector table to 37 464 rows (148 MB on disk after cleaning old versions; it had grown to 1.8 GB of versions). The vector store also refuses
to write, and never searches, a row of another language, so a store restored from an older backup cannot bring Russian vectors back into search.
To search Russian again, set `VECTOR_LANGUAGES=uz,ru`, clear `FTS_EXCLUDE_LANGUAGES` and run `scripts/embed_missing.py --extend-chunks` style
re-embedding (about 10 M tokens, about $0.10).

## Backup and restore

```bash
scripts/backup.sh --keep 14            # data/backups/legal_rag_backup_<time>/ : SQLite online backup + verified LanceDB copy
scripts/restore.sh <backup folder>     # server must be stopped; the current store is moved to data/backups/pre_restore_<time>/
```

## Checking a change

```bash
.venv/bin/python -m pytest -q                                                    # about 50 s, no network
.venv/bin/python -m pyflakes src scripts tests                                   # must print nothing (CI runs it too)
.venv/bin/python scripts/stress_eval.py --retrieval-only --baseline <old report>  # exit code 1 on a regression > 3 points
.venv/bin/python scripts/stress_eval.py --only @data/golden_dataset/stress_dev_split.json --profile prod \
       --judge-model <another model> --baseline <old report>          # end to end: answers + judge + deterministic checks
.venv/bin/python scripts/profile_retrieval.py --limit 12                          # where retrieval time goes
.venv/bin/python scripts/diagnose_question.py s075                                # why one question misses its unit
.venv/bin/python scripts/calibrate_scope.py --dataset data/golden_dataset/heldout_v1.json   # scope gate separation
```

`data/golden_dataset/heldout_v1.json` (55 in-scope and 40 out-of-scope questions written from sampled units that no other
set uses) is a held-out set: do not tune on it. Its sha256 is in `heldout_v1.manifest.json`.

An evaluation judge should be a different model from the generator (`--judge-model`). Every evaluation call is paid: check the OpenRouter
key first (`GET /api/v1/key`, field `limit_remaining`): a retrieval-only benchmark of 200 questions costs about $0.12 of Jev.

## Security notes

- Administration needs `ADMIN_API_KEY`; the loopback shortcut is off by default as soon as a key is configured.
- Public question endpoints: 256 KB body limit, per-IP rate limit (the real address behind nginx via uvicorn `--proxy-headers`),
  daily cap on generated answers, security headers and a CSP.
- Rotate any key that was ever printed in logs or committed: the gateway key in commit `13001dc` (scripts/eval_3way_sample.py,
  not pushed), the GitHub token inside the `origin` URL, and the Tuzuk JWT in the public history (`ea3093c`).

## Claim check (SUPPORT_CHECK_ENABLED): measured, left off

`scripts/replay_answers.py` regenerates the answers of an earlier report on the same frozen contexts (no retrieval; the chat calls are paid) and judges them:
53 stress dev questions, generator `muse-spark-1.3`, judge `muse-spark-1.2`. Without the check 98.1% correct / 1.9% wrong; with it 96.2% / 1.9%,
and it changed none of the 53 answers while adding 1.7 s (2.7 s -> 4.4 s). The earlier end-to-end run counted 3 "wrong" answers among 59 on the same
contexts, so the 2-6% of answers that add a plausible condition is generation noise the check does not catch. Left off.

```bash
.venv/bin/python scripts/replay_answers.py --contexts <stress report with context_ids> --arms off,on --report replay.json
```
