# FINAL REPORT - agent/max-quality run (2026-10-25)

Branch `agent/max-quality` (local only, never pushed). Baseline commit `1b53fea` (the previous sessions' uncommitted work),
start balance $10.00. Every number below comes from a command that can be re-run (section 8).

## 1. Summary

**RAG ning barcha vazifalari xatosiz ishlayapti** - every readiness criterion below is met and each is proven by a command
that can be re-run (section 8): 678 tests pass with none skipped; on the 76-question gold set recall@5 is 0.964, every
citation is valid, nothing is invented, every out-of-corpus question is refused and none in-corpus is; the server survives
every error scenario with 177.6 MB idle; the admin panel works; a clean install from the README works. Spent $0.74 of
the $4 allowed. What is left (section 7) is the owner's editorial work and decisions, not failures.

## 2. Criteria

| Criterion | Result | Proof |
|---|---|---|
| All tests pass, none deleted or skipped | 678 passed, 0 skipped (the baseline skipped 2; both now run) | `pytest -q -rs`; also inside the fresh clone of `eval/clean_install.sh` |
| Citation correctness 100% (validator) | 100.0% of 76 answers | gold run of cycle 13 (`EVAL_HISTORY.md`, `eval/reports/latest.json`) |
| Invented articles / numbers 0 | 0 articles, 0 numbers | same run (validator + ungrounded-number check) |
| Honest refusal 100% | 100.0% of out-of-corpus questions refused; false refusal 0.0% | same run |
| recall@5 >= 0.90 | 0.964 (gold v2); 0.936 with the baseline's v1 slots | same run |
| Repealed-norm references 0 | 0; repealed-act traps answered right 100.0% | same run |
| Server never crashes on error scenarios | 30/30: invalid JSON, wrong type, unknown language, empty / blank / over-long question, oversized body (413), injection (400), unknown route, admin without / with a wrong key, provider 429 / 500 / hang (a clear degraded answer, the hang in 46 s), SSE client drop, 300 questions without a 5xx, no key in the logs; the server is alive after each | `eval/check_server.py` -> `eval/reports/server_check.json` |
| Idle RAM < 350 MB, /health ok | 177.6 MB idle; +1.1 MB over 300 questions; /health "healthy" | same check |
| /admin-v2 sections error-free | all 7 sections (5 required) opened in the browser at `dce19fa` on a copy of the store: 44 requests all 200, 0 console errors, data shown in every section, no emoji | browser check of this run |
| No emoji in answers and UI | 0 answers with emoji; admin UI, Telegram formatting, admin API, logs emoji-free | gold run (`emoji_answers`), `tests/test_no_emoji.py` |
| Clean install per README | CLEAN INSTALL OK at `dce19fa`: venv, `pip check`, 678 tests, one act from Lex.uz, corpus audit, server, /health, one answered and cited question, key not in the log | `eval/clean_install.sh <empty folder>` |
| Prompt injection | 0 of 6 injected instructions followed (fake article, injected number, system prompt request); 3 of 6 refused as manipulation | `eval/run_eval.py --gold eval/injection_set.jsonl --offline` |
| Budget | $0.74 spent of $4; balance $9.26 (floor $6) | `BUDGET.md` (balance read from the OpenRouter API before and after every run) |

## 3. Metrics: baseline and final

Gold set `eval/gold_set.jsonl` (76 questions: 26 uz, 25 ru, 25 en; short, complex, multi-article, repealed-act traps,
out-of-corpus, misspelled / mixed language). Production path (`eval/run_eval.py`), production model
`deepseek/deepseek-v4-flash-0731`, embeddings `baai/bge-m3`.

| Metric | Baseline (`1b53fea`, 75 questions, v1 slots) | Final (cycle 13, 76 questions, v2 slots) | Final scored with v1 slots |
|---|---|---|---|
| recall@5 | 0.891 | **0.964** | 0.936 |
| MRR | 0.813 | **0.921** | 0.878 |
| Valid citations | 95.5% | **100.0%** | |
| Invented articles / ungrounded numbers | 0 / 1 | **0 / 0** | |
| Honest refusal (out of corpus) | 100% | **100%** | |
| False refusal (in corpus) | 2.9% | **0.0%** | |
| Answer in the question's language | 100% | 100% | |
| Key facts present | 100% | 100% | |
| Repealed references | 0 | 0 | |
| Latency p50 / p95 (live estimate) | 13.5 s / - | 15.5 s / 42.2 s | |
| Cost per question (live) | $0.00135 | **$0.00082** | |

v2 slots (cycle 4 on) accept a second unit that states the same rule (DECISIONS.md); the last column scores the final run with
the baseline's slots, so the gain is not a measurement change. Latency is higher because answers now go through one guarded
repair round and a provider that is cheaper but slower (Baidu fp8); the cost per question fell by 39%.

Every run is a row of `EVAL_HISTORY.md` (baseline + 13 cycles, all criteria met from cycle 2; cycle 7 hit a DNS outage, is marked INVALID and was
re-run).

## 4. Bugs fixed (file - cause - test)

| # | Where | What was wrong | Test |
|---|---|---|---|
| 1 | `src/generation/guards.py`, `validator.py` | The model cited ids it was never given (`vmq_62_2022_a9_p_46`, extrapolated from a neighbour); the validator silently dropped them and failed the answer (3 of 66 answers) | `tests/test_answer_guards.py` (unknown citation is repaired; validator names removed ids) |
| 2 | data + `src/ingestion/corpus_builder.py` | 284 Russian texts belonged to another point (repeated numbering in annexes paired with the first Russian unit); Russian questions were answered from the wrong text | `tests/test_russian_pairing.py`, `tests/test_translation_audit.py` |
| 3 | `src/retrieval/hierarchy.py` | Laws with old numbering (938-XII, 343-I, 258-II) weighed like departmental orders; Huquq+ commentary weighed above the Constitution (1.00): the Pension Law fell out of the candidates | `tests/test_hierarchy_weights.py` |
| 4 | `src/retrieval/jev_ranker.py` (scope rule) | "facsimile signature" (Law 641 art. 29) refused as out of scope | `tests/test_hierarchy_weights.py::test_every_right_of_the_disability_law_is_in_scope` |
| 5 | `src/generation/answer_checks.py` | Numbers the statute writes in words ("o'n to'rt kun") counted as invented when the answer wrote "14" | `tests/test_answer_checks.py` (number words) |
| 6 | `src/retrieval/pipeline.py`, `src/gateway/service.py` | A provider that hangs held a request for minutes (no deadline on embedding, translation, scope, ranking) | `tests/test_retrieval_deadline.py`; `eval/check_server.py` (hang: 46 s, sources-only answer) |
| 7 | `tests/conftest.py` | `monkeypatch.setattr("src.api.app.get_cache")` hit the lazily exported FastAPI object when the test ran first | the file passes alone and in the suite |
| 8 | `src/gateway/formatting.py`, `src/api/routes/admin.py`, `src/ingestion/universal_engine.py` | Emoji in bot answers (headings), in the admin API and in logs | `tests/test_gateway_api.py`, `tests/test_no_emoji.py` |
| 9 | `src/storage/fts_store.py` | Document search ran one full scan per act: `GET /api/v1/inclusive/documents?q=641` took 90 s (public endpoint) | `tests/test_document_search.py` (one pass; 0.6 s live) |
| 10 | `tests/test_evaluation_regression.py`, `tests/test_query_subquestions.py` | Two tests skipped (built corpus absent in a fresh clone; a live test behind an env flag) | label test checks the shipped seed; the live check is gold item uz26 |
| 11 | data | U+FFFD broken characters in 3 units; the next section's heading glued to 18 units | `tests/test_corpus_audit.py`; `scripts/audit_corpus.py` (exit 0) |
| 12 | `src/storage/vector_store.py` | LanceDB deprecation warning on every vector search (4-6 log lines a question) | `tests/test_vector_search_logging.py` |
| 13 | `src/generation/prompts.py` | Answers cached before the data fixes (e.g. quoting a shifted Russian text) would still be served for 24 h | `tests/test_answer_guards.py::test_cache_key_separates_scripts_and_answer_versions` |
| 14 | `src/ingestion/lex_structured.py` + data | A point after a repealed point was glued to the previous one (VMQ-62 annex 9 point 44 held 46-48, the criteria of groups I-III): 730 points in 85 acts; re-imported (+820 units) | `tests/test_lex_structured_clauses.py::test_a_point_after_a_repealed_one_starts_its_own_unit` |
| 15 | `src/retrieval/repeal_notices.py`, `pipeline.py` | The clause repealing a named act was the 8th of 8 contexts and fell out when the corpus grew; answers described the repealed act as current law | `tests/test_repeal_notices.py` (strict matching, no false notice for an act in force) |
| 16 | `src/clients/openrouter.py`, `src/config.py` | Fallback routing could reach providers 3-10x dearer ("unknown" quantization, no price cap) | `tests/test_generation.py`, `tests/test_llm_routing.py` |
| 17 | `src/retrieval/pipeline.py` | A transient ranker failure discarded the scope judgement (1.0) and the lexical gate refused an English question | `tests/test_gate_scope_rescue.py` |
| 18 | `src/retrieval/repeal_notices.py` | Repeal notices matched an act by its number only: an act in force could be called repealed, a partial repeal counted as whole | `tests/test_repeal_notices.py` (type and year must match; only the item that lost force) |
| 19 | `src/gateway/service.py` | An answer built after a retrieval timeout (sources-only fallback) was cached for 24 h | `tests/test_answer_integrity.py::test_an_answer_from_the_timed_out_retrieval_is_not_cached` |
| 20 | `src/retrieval/pipeline.py` | The scope rescue could override refusals other than the lexical gate's | `tests/test_gate_scope_rescue.py` |
| 21 | `src/storage/fts_store.py` | Document search lost Russian words (SQLite `lower()` is ASCII-only) and served stale results after a write | `tests/test_document_search.py::test_russian_words_find_the_act_as_before` |
| 22 | `src/generation/answer_checks.py` | Number words matched inside other words ("yuz" in "yuzasidan"); "7.5 soat" from "yetti soatu o'ttiz daqiqa" called invented | `tests/test_answer_checks.py` |
| 23 | `src/generation/validator.py`, `guards.py` | A bracket listing several ids was read as one id; the repair round moved an unsupported sentence to another source instead of removing it | `tests/test_answer_guards.py` |
| 24 | `src/clients/openrouter.py` | With the price cap, no provider under it meant a failed answer | `tests/test_llm_routing.py::test_no_provider_under_the_price_cap_retries_once_without_it` |
| 25 | `eval/run_eval.py` | The criteria passed when an answer was not generated; a rejected injected value ("not 45", "no provision for 45 days") counted as followed; empty completions were cached | `tests/test_eval_runner.py` |
| 26 | `scripts/classify_refresh_changes.py` + editorial data | Removed text counted as "re-parse only": 3 cards closed wrongly (reopened); 38 others closed through the editor's keep path | `tests/test_classify_refresh_changes.py` |
| 27 | `src/ingestion/corpus_builder.py` + data | The Russian text of a split point stayed inside the previous point (60 units moved) | `tests/test_translation_audit.py`, `tests/test_corpus_audit.py` (russian_overflow = 0) |
| 28 | `src/ingestion/lex_structured.py` | A repeal note naming several points ("5 va 6-bandlar", "5-7") freed only the first | `tests/test_lex_structured_clauses.py::test_notes_that_repeal_several_points_at_once_are_understood` |
| 29 | `scripts/audit_translations.py` + data | The vector cache was keyed by id and reused after a text changed; with a text key the audit found 9 Russian texts of VMQ-319 annex 3 that the re-import had paired again (removed) | `tests/test_translation_audit.py`; audit: 0 misaligned |

Rows 18-29 come from an adversarial review (three reviewers per area: retrieval, generation, ingestion), each finding
reproduced before it was fixed.

## 5. Main decisions (DECISIONS.md has all, each with how to undo it)

- Gold slots accept every unit that states the same rule (v2 from cycle 4); the final run is also scored with the v1 slots.
- 284 + 9 Russian texts that translate another unit were removed (the Uzbek text is authoritative); 60 moved to their own point.
- Re-imported 85 acts whose points were glued after a repealed point (+820 units), evaluated on a copy first (recall@5 0.95 -> 0.979).
- LLM provider pinned: Baidu then DeepInfra, fp8 or better, price cap $0.10 / $0.30 per M tokens; one retry without the cap.
- Embedding model: qwen3-embedding-8b measured better on a copy (dense recall@5 0.71 -> 0.84); production stays on bge-m3 until the owner decides.
- 14 editorial cards with new Lex.uz text left open for the owner; VMQ-240 refresh left for manual review; 55 coarse units not split by regex.
- Questions that carry an instruction to the assistant are refused by the scope judge's "manipulation" class (safe, kept).

## 6. Money

| | USD |
|---|---|
| Balance at the start (OpenRouter API) | 10.00 |
| Balance at the end (OpenRouter API) | 9.26 |
| Spent in this run (all calls: evals, re-import embeddings, audits, comparisons) | 0.74 |
| Of which the qwen3 embedding comparison (store copy) | ~0.08 |
| Limit / stop line / floor | 4.00 / 3.50 / balance 6.00 - never reached |

The gold set replays cached model responses, so a cycle with no change to prompts or contexts costs nearly nothing; a live
question costs $0.00082. Every row is in `BUDGET.md`.

## 7. Remaining risks and open items

1. **14 open editorial notifications** (owner): new Lex.uz text in VMQ-119, VMQ-313, VMQ-62, VMQ-482; text removed from VMQ-183, VMQ-223, PF-79. Until resolved in the admin panel (Bildirishnomalar), the Huquq+ posts linked to those acts are kept out of answers.
2. **VMQ-240 (2008)** was skipped by the refresh's mass-removal guard (34 of 39 units would go); check it on Lex.uz, then `refresh --allow-mass-removal` (BLOCKERS.md).
3. **55 units** still hold later point numbers (quoted amendment lists, tables): the text is found, citations are coarser.
4. **Embedding switch** (owner's decision): qwen3-embedding-8b is better on the gold set, same price; steps in `docs/EMBEDDING_COMPARISON.md`.
5. **Latency**: p50 ~15.5 s, p95 ~42 s (guarded repair round, slower cheap provider). Streaming shows the first words earlier; a faster provider costs more.
6. **The gold set was written by the agent** from the corpus text, not checked by a lawyer; 76 questions cannot cover every norm. Results on real users' questions can be lower.
7. **Every refresh can bring back misaligned Russian texts** (an annex numbered differently in the Russian edition): run `scripts/audit_translations.py --apply` and `scripts/audit_corpus.py` after each refresh (docs/OPERATIONS.md).
8. Eval cost counts only completed calls; a call cancelled by a deadline is not in the run's cost (it is in the OpenRouter balance, which BUDGET.md reads).

## 8. Check it yourself

```bash
.venv/bin/python -m pytest -q -rs                      # all tests, offline; -rs lists skips (none)
.venv/bin/python eval/run_eval.py --offline            # gold set from the cached model responses (free)
.venv/bin/python eval/check_server.py                  # idle RAM, /health, bad input, failing provider, leaks, secrets
.venv/bin/python scripts/audit_corpus.py               # corpus quality gate (exit 0)
eval/clean_install.sh /tmp/clean-rag                   # README setup in a fresh clone (one paid question)
.venv/bin/python eval/run_eval.py --gold eval/injection_set.jsonl --offline   # prompt injections
```
