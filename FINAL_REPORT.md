# FINAL REPORT - agent/max-quality run (2026-10-25)

Branch `agent/max-quality` (local only, never pushed). Baseline commit `1b53fea` (the previous sessions' uncommitted work),
start balance $10.00. Two rounds: the readiness work (cycles 1-13), then the owner's second brief (quality first, then low
cost; switch to qwen3-embedding if it really is better; remove excess code; every act complete and current; an old rule
never shown as current), cycles 14-15. Every number below comes from a command that can be re-run (section 8).

## 1. Summary

**RAG ning barcha vazifalari xatosiz ishlayapti** - every readiness criterion is met on the final commit and each is proven
by a re-runnable command: 646 tests pass with none skipped; on the 76-question gold set recall@5 is 0.971 and MRR 0.964,
every citation is valid, nothing is invented, every out-of-corpus question is refused and none in-corpus is; the server
survives every error scenario at 178 MB idle; the admin panel works; a clean install from the README works. The corpus
was re-read from Lex.uz (534 acts, all in force, current editions) and a repealed unit can no longer reach an answer.
On an independent held-out set (95 questions written by another process from randomly sampled units) 77% of the answered
in-scope questions are correct and every out-of-scope question is refused - the honest measure of what to expect from
real users (section 3). Spent $1.34 of the $4 allowed.

## 2. Criteria

| Criterion | Result | Proof |
|---|---|---|
| All tests pass, none skipped | 646 passed, 0 skipped (baseline skipped 2). 50 tests went with removed code (section 4), none of remaining code | `pytest -q -rs`; also in the fresh clone of `eval/clean_install.sh` |
| Citation correctness 100% (validator) | 100% of 76 answers | cycle 15, `EVAL_HISTORY.md`, `eval/reports/latest.json` |
| Invented articles / numbers 0 | 0 / 0 | same run |
| Honest refusal 100% | 100% of out-of-corpus questions refused; false refusal 0% | same run |
| recall@5 >= 0.90 | 0.971 (gold v2); 0.943 with the baseline's v1 slots | same run |
| Repealed-norm references 0 | 0; repealed-act traps 100%; repealed units are dropped from every answer's sources | same run; `tests/test_retrieval.py::test_a_repealed_unit_is_never_an_answer_source` |
| Server never crashes on error scenarios | 30/30: invalid JSON, wrong type, unknown language, empty / blank / over-long question, oversized body, injection, unknown route, admin without / with a wrong key, provider 429 / 500 / hang (honest HTTP 503 "temporarily unavailable" in 8 / 13 / 46 s), SSE client drop, 300 questions without a 5xx, no key in the logs | `eval/check_server.py` -> `eval/reports/server_check.json` |
| Idle RAM < 350 MB, /health ok | 178 MB idle; +3.6 MB over 300 questions; /health "healthy" (details: embedding model matches the store) | same check; `/health/details` |
| /admin-v2 sections error-free | all 7 sections (5 required) on the final code and production store: every API call 200, 0 console errors, no emoji | browser check, 2026-10-25 20:20 |
| No emoji in answers and UI | none in answers, admin UI, Telegram formatting, admin API, logs; README headings cleaned too | `tests/test_no_emoji.py`, gold run |
| Clean install per README | CLEAN INSTALL OK at `1f71243` (643 tests in the clone, one act fetched and embedded with qwen3, /health, one cited answer, key not in the log) | `eval/clean_install.sh <empty folder>` |
| Prompt injection | 0 of 6 injected instructions followed; 3 of 6 refused as manipulation | `eval/run_eval.py --gold eval/injection_set.jsonl --offline` |
| Budget | $1.34 spent of $4; balance $8.66 (floor $6) | `BUDGET.md` (OpenRouter balance before and after every run) |

## 3. Metrics

Gold set `eval/gold_set.jsonl` (76 questions: 26 uz, 25 ru, 25 en). Production path, chat model
`deepseek/deepseek-v4-flash-0731`.

| Metric | Baseline (`1b53fea`, bge-m3) | Cycle 13 (bge-m3) | **Final, cycle 15 (qwen3, refreshed corpus)** |
|---|---|---|---|
| recall@5 (v2 slots / baseline's v1 slots) | - / 0.891 | 0.964 / 0.936 | **0.971 / 0.943** |
| MRR (v2 / v1) | - / 0.813 | 0.921 / 0.878 | **0.964 / 0.921** |
| Valid citations | 95.5% | 100% | **100%** |
| Invented articles / ungrounded numbers | 0 / 1 | 0 / 0 | **0 / 0** |
| Honest refusal / false refusal | 100% / 2.9% | 100% / 0% | **100% / 0%** |
| Language, key facts, repealed-act traps | 100% | 100% | **100%** |
| Latency p50 / p95 (live estimate) | 13.5 s / - | 15.2 s / 39 s | 21 s / 40 s |
| Cost per question (live) | $0.00135 | $0.00082 | **$0.0009** |

Held-out set `data/golden_dataset/heldout_v1.json` (55 in-scope, 40 out-of-scope; questions written from sampled units
that no other set uses; never tuned on). `scripts/stress_eval.py --profile prod`, judged by the chat model:

| Held-out measure | Result |
|---|---|
| Out-of-scope questions refused | **100%** (37 + 3 ambiguous) |
| In-scope: correct / partial / wrong / refused | 67% / 11% / 9% / 13% (37 / 6 / 5 / 7 of 55) |
| Answered in-scope questions judged correct | **77%** (37 of 48; 90% correct or partial) |
| Expected unit among the answer's sources / in the candidate pool | 71% / 93% |

The gold set was written by the agent and is easier; the held-out set is the realistic figure. Of its 7 refusals, some are
outside the service's stated mission (an advocate's licence, orphanage educators' pay); the others are peripheral social
questions the scope judge refuses (a birth allowance, a housing loan). A clarified scope definition did not help on the
tuning set, so it was not changed (DECISIONS.md).

Every run is a row of `EVAL_HISTORY.md` (baseline + 15 cycles and the comparison runs; cycle 7 hit a DNS outage, is marked
INVALID and was re-run).

## 4. Bugs fixed (file - cause - test)

| # | Where | What was wrong | Test |
|---|---|---|---|
| 1 | `src/generation/guards.py`, `validator.py` | The model cited ids it was never given; the validator silently dropped them and failed the answer | `tests/test_answer_guards.py` |
| 2 | data + `src/ingestion/corpus_builder.py` | 284 Russian texts belonged to another point (repeated annex numbering) | `tests/test_russian_pairing.py`, `tests/test_translation_audit.py` |
| 3 | `src/retrieval/hierarchy.py` | Old-numbered laws weighed like orders; Huquq+ commentary above the Constitution | `tests/test_hierarchy_weights.py` |
| 4 | `src/retrieval/jev_ranker.py` | "facsimile signature" (Law 641 art. 29) refused as out of scope | `tests/test_hierarchy_weights.py` |
| 5 | `src/generation/answer_checks.py` | Numbers the statute writes in words counted as invented | `tests/test_answer_checks.py` |
| 6 | `src/retrieval/pipeline.py`, `src/gateway/service.py` | A hanging provider held a request for minutes | `tests/test_retrieval_deadline.py`; server check |
| 7 | `tests/conftest.py` | Test order changed what a string patch hit | the suite in any order |
| 8 | formatting, admin API, ingestion logs | Emoji in answers, admin API and logs | `tests/test_no_emoji.py` |
| 9 | `src/storage/fts_store.py` | Document search took 90 s (one scan per act) | `tests/test_document_search.py` |
| 10 | tests | Two tests skipped | they run |
| 11 | data | Broken characters (3 units), glued headings (18) | `tests/test_corpus_audit.py`; `scripts/audit_corpus.py` |
| 12 | `src/storage/vector_store.py` | A deprecation warning on every vector search | `tests/test_vector_search_logging.py` |
| 13 | `src/generation/prompts.py` | Answers cached before the data fixes were still served | `tests/test_answer_guards.py` |
| 14 | `src/ingestion/lex_structured.py` + data | A point after a repealed point was glued to the previous one (730 points, 85 acts) | `tests/test_lex_structured_clauses.py` |
| 15 | `src/retrieval/repeal_notices.py` | The clause repealing a named act fell out of the contexts | `tests/test_repeal_notices.py` |
| 16 | `src/clients/openrouter.py`, `src/config.py` | Routing could reach providers 3-10x dearer | `tests/test_llm_routing.py` |
| 17 | `src/retrieval/pipeline.py` | A transient ranker failure became a refusal | `tests/test_gate_scope_rescue.py` |
| 18-29 | retrieval, generation, ingestion (adversarial review) | strict repeal notices; no caching after a timeout; Russian document search; exact number words; list-bracket ids; remove-not-move repair; price-cap retry; eval criteria; refresh classifier; Russian overflow (60 units); multi-point repeal notes; text-keyed audit cache and 9 VMQ-319 texts | see `git log` and the test files named there |
| 30 | data (full refresh) | 36 acts had newer text on Lex.uz than in the store (Law 641 art. 28, Labour Code art. 161, Tax Code arts. 111-112, VMQ-405 point 29 deadline 16th -> 26th, ...); VMQ-240 had a new edition | `scripts/build_disability_corpus.py refresh` report; audits clean |
| 31 | `src/retrieval/status_filter.py` | A repealed unit stayed in the answer's sources with a label, relying on the model to say so | `tests/test_retrieval.py::test_a_repealed_unit_is_never_an_answer_source` |
| 32 | `src/api/cache.py`, `src/gateway/service.py` | Answers cached before a refresh run (another process) were served for up to 24 h, from the RAM layer even after the database was cleared | `tests/test_answer_integrity.py::test_cached_answers_go_when_the_corpus_changes_even_in_another_process` |
| 33 | `src/storage/fts_store.py` | The article cache kept serving a repealed act after another process's write until someone cleared it | `tests/test_storage.py::test_fts_article_cache_sees_a_write_of_another_process` |
| 34 | `src/storage/hybrid_store.py`, `src/retrieval/hybrid_retriever.py` | Nothing recorded which model made the vectors (rows carried the metadata label "baai/bge-m3"); a restored backup or a config change would mix models silently | `tests/test_embedding_marker.py` |
| 35 | `scripts/audit_translations.py` | The audit followed the service's model; with qwen3 its bge-m3 thresholds would remove correct Russian texts | `tests/test_embedding_options.py::test_the_translation_audit_embeds_with_its_calibrated_model` |
| 36 | `src/clients/openrouter.py` | The output size was sent to any model, not only the configured one | `tests/test_embedding_options.py::test_another_model_gets_its_native_size` |
| 37 | `src/gateway/review.py` | The review reply could come back empty: the model's default reasoning used the whole 4096-token budget | `tests/test_review_endpoint.py::test_the_review_call_states_its_reasoning_and_leaves_room_for_the_verdict` |
| 38 | `scripts/stress_eval.py`, `eval/run_eval.py` | The judge returned empty for 16 of 92 items (same cause); the injection check misread "not supported" after a value | `tests/test_eval_runner.py` |
| 39 | `src/api/routes/admin.py` + 6 modules | Legacy upload / any-website ingestion endpoints (unused by the panel) could put non-Lex.uz text into the legal corpus; removed with their code | the corpus is fed only through `/api/v1/admin/corpus/*` and the build script |
| 40 | `src/gateway/service.py`, `src/generation/generator.py`, `src/clients/openrouter.py` | With the model down, hung or the budget used up, the service "answered" with quoted norms picked by search alone (no model); at 80% of the budget it skipped query rewriting and follow-up context. Now: HTTP 503 "temporarily unavailable" in the question's language, stored answers still served, quality independent of the budget; `src/generation/degraded.py` removed | `tests/test_security_and_regressions.py::test_a_used_up_budget_answers_unavailable_at_once_and_still_serves_stored_answers`, `tests/test_answer_guards.py::test_no_answer_is_written_when_every_model_fails`; server check 30/30; gold replay all criteria |

## 5. Main decisions (DECISIONS.md has all, each with how to undo it)

- Embeddings switched to **qwen/qwen3-embedding-8b** (owner-approved): gold MRR 0.921 -> 0.971 on the same data, dense recall@5 0.707 -> 0.807, same price; semantic-cache (0.95) and gate (0.82) thresholds re-checked and kept.
- The store records its embedding model; a mismatch means full-text search only and `/health` degraded, never mixed vectors.
- Every registry act re-read from Lex.uz into a copy, evaluated, then swapped in; 5 acts added after a new discovery run (VMQ-555 of 2026 on social service centres among them); VMQ-240 replaced by its current edition.
- Refresh cards whose post cannot be affected are closed with the change noted; 15 that may be affected stay for the editor (one post states a deadline that changed from the 16th to the 26th).
- Repealed units never reach an answer; cached answers and articles never outlive a corpus change.
- Excess code removed: 19 one-off scripts, the legacy ingestion endpoints and 7 modules, the old evaluation harness, python-multipart.
- Scope gate and claim check left as they are (the measurements did not support a change).
- From round one: gold slots accept every unit stating the same rule; 293 misaligned Russian texts removed, 60 moved; provider pinned (Baidu, then DeepInfra; fp8 or better; price cap).

## 6. Money

| | USD |
|---|---|
| Balance at the start (OpenRouter API) | 10.00 |
| Balance at the end (OpenRouter API) | 8.66 |
| Spent in this run | 1.34 |
| Of which: two full re-embeddings with qwen3 (one lost to a machine restart) | ~0.35 |
| Limit / stop line / floor | 4.00 / 3.50 / balance 6.00 - never reached |

A live question costs about $0.0009; a regression cycle that replays cached responses costs nearly nothing.

## 7. Remaining risks and open items

1. **15 open editorial notifications** (owner, admin panel > Bildirishnomalar): the linked Huquq+ posts stay out of answers until resolved. Post uz:8594 says the VMQ-405 subsidy deadline is the 16th; it is now the 26th.
2. **Held-out accuracy**: 77% of answered independent questions correct, 9% of in-scope answers wrong (an unsupported conclusion added to the right article), 13% refused. Real users will see errors of this kind; the disclaimer and the citations let them check.
3. **Latency**: p50 ~21 s, p95 ~40 s (guarded answers, cheap provider). Streaming shows the first words earlier.
4. **54 units** still hold later point numbers (quoted amendment lists, tables): found, with coarser citations.
5. **Refreshes**: run `scripts/audit_translations.py --apply`, `scripts/audit_corpus.py` and `scripts/classify_refresh_changes.py --resolve --keep-untouched` after each one (docs/OPERATIONS.md).
6. The held-out judge is the chat model grading its own answers; an independent judge would be stricter or kinder.

## 8. Check it yourself

```bash
.venv/bin/python -m pytest -q -rs                      # all tests, offline; -rs lists skips (none)
.venv/bin/python eval/run_eval.py --offline            # gold set from the cached model responses (free)
.venv/bin/python eval/check_server.py                  # idle RAM, /health, bad input, failing provider, leaks, secrets
.venv/bin/python scripts/audit_corpus.py               # corpus quality gate (exit 0)
eval/clean_install.sh /tmp/clean-rag                   # README setup in a fresh clone (one paid question)
.venv/bin/python eval/run_eval.py --gold eval/injection_set.jsonl --offline   # prompt injections
```
