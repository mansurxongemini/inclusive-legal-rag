# EVAL_HISTORY

Gold set: eval/gold_set.jsonl. Columns: recall@5, MRR, valid citations %, invented articles/ungrounded numbers, honest refusal %, false refusal %, answer language %, key facts %, repealed references, p50 latency (ms, live estimate), new spend (USD), all criteria met.

| when | label | n | recall@5 | MRR | cit.valid | invented | refusal ok | false refusal | lang ok | facts | repealed | p50 ms | spend $ | all met |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-25T00:39 | baseline | 75 | 0.891 | 0.813 | 95.5 | 0/1 | 100.0 | 2.9 | 100.0 | 100.0 | 0 | 13456 | 0.10111 | no |
| 2026-10-25T01:09 | cycle 1: guard ids, ru alignment, hierarchy, scope | 76 | 0.921 | 0.856 | 100.0 | 0/1 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 14772 | 0.047 | no |
| 2026-10-25T01:23 | cycle 2: number words, retrieval deadline | 76 | 0.921 | 0.856 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 16481 | 0.00185 | yes |
| 2026-10-25T07:06 | cycle 3: emoji-free answers, one-pass document search [tests: 612 passed, 1 warning; server: 30/30] | 76 | 0.921 | 0.856 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 17091 | 0.00082 | yes |
| 2026-10-25T07:12 | cycle 4: gold v2 (verified slot alternatives), README [tests: 612 passed, 1 warning; server: 30/30] | 76 | 0.95 | 0.899 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 15732 | 0.00563 | yes |
| 2026-10-25T07:19 | cycle 5: corpus gate (U+FFFD, glued headings), quiet vector search [tests: 617 passed, 1 warning; server: 30/30] | 76 | 0.95 | 0.899 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 15834 | 0.0006 | yes |
| 2026-10-25T07:28 | cycle 6: answer version, injection set, parser fix (code), conftest [tests: 620 passed, 1 warning; server: 30/30] | 76 | 0.95 | 0.899 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 16098 | 0.00126 | yes |
| 2026-10-25T08:33 | cycle 7: re-imported 85 acts (+820 units), repeal notices, provider routing (baidu, fp8, price cap), scope rescue [tests: 633 passed, 1 warning; server: 30/30] [INVALID: DNS outage - 126 model calls failed with 'Temporary failure in name resolution'; rerun below] | 76 | 0.679 | 0.647 | 100.0 | 0/0 | 100.0 | 28.6 | 100.0 | 71.8 | 0 | 14290 | 0.04396 | no |
| 2026-10-25T08:38 | cycle 7 (rerun after the DNS outage): re-imported acts, repeal notices, provider routing, scope rescue [tests: 633 passed, 1 warning; server: 30/30] | 76 | 0.964 | 0.921 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 14065 | 0.02348 | yes |
| 2026-10-25T08:48 | cycle 8: embedding options (off by default), query-embedding path, dense-only probe [tests: 635 passed, 1 warning; server: 30/30] | 76 | 0.964 | 0.921 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 15411 | 6e-05 | yes |
| 2026-10-25T12:18 | cycle 9: review fixes (repeal notices strict, no caching after retrieval timeout, rescue only over the lexical gate, Russian document search), hours-as-decimal check [tests: 645 passed, 1 warning; server: 30/30] | 76 | 0.964 | 0.921 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 15418 | 0.00154 | yes |
| 2026-10-25T12:34 | cycle 10: clean-install check, embedding comparison docs (production unchanged) [tests: 645 passed, 1 warning; server: 30/30] | 76 | 0.964 | 0.921 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 15812 | 0 | yes |
| 2026-10-25T12:43 | cycle 11: review fixes (exact number words, list-bracket ids, remove-not-move repair, price-cap retry, stricter eval criteria) [tests: 668 passed, 1 warning; server: 30/30] | 76 | 0.964 | 0.921 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 16574 | 0.00041 | yes |
| 2026-10-25T13:04 | cycle 12: ingestion review fixes (60 Russian points moved to their units, multi-point repeal notes, text-keyed audit cache), 3 cards reopened [tests: 674 passed, 1 warning; server: 30/30] | 76 | 0.964 | 0.921 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 15171 | 0.00969 | yes |
| 2026-10-25T13:35 | cycle 13 (final state): injection check negation window, 9 misaligned Russian texts of VMQ-319 removed [tests: 678 passed, 1 warning; server: 30/30] | 76 | 0.964 | 0.921 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 15533 | 0.00098 | yes |
