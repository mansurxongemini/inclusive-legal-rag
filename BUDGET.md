# BUDGET (agent/max-quality run)

Limits: spend at most $4.00; stop paid calls at $3.50 spent; balance must never fall below $6.00.
Production model unchanged: chat `deepseek/deepseek-v4-flash-0731`, embeddings `baai/bge-m3`.

| When | Event | total_credits | total_usage | balance | spent this run |
|---|---|---|---|---|---|
| 2026-10-25 00:27 | start (GET /api/v1/credits) | 10.00 | 0.00 | 10.00 | 0.00 |
| 2026-10-25 00:34 | eval 20261025_003407 | 10.00 | 0.0001 | 9.9999 | 0.0001 |
| 2026-10-25 00:39 | eval baseline | 10.00 | 0.1086 | 9.8914 | 0.1086 |
| 2026-10-25 01:09 | eval cycle 1: guard ids, ru alignment, hierarchy, scope | 10.00 | 0.1960 | 9.8040 | 0.1960 |
| 2026-10-25 01:23 | eval cycle 2: number words, retrieval deadline | 10.00 | 0.2041 | 9.7959 | 0.2041 |
| 2026-10-25 07:06 | eval cycle 3: emoji-free answers, one-pass document search [tests: 612 passed, 1 warning; server: 30/30] | 10.00 | 0.2047 | 9.7953 | 0.2047 |
| 2026-10-25 07:12 | eval cycle 4: gold v2 (verified slot alternatives), README [tests: 612 passed, 1 warning; server: 30/30] | 10.00 | 0.2130 | 9.7870 | 0.2130 |
| 2026-10-25 07:19 | eval cycle 5: corpus gate (U+FFFD, glued headings), quiet vector search [tests: 617 passed, 1 warning; server: 30/30] | 10.00 | 0.2148 | 9.7852 | 0.2148 |
| 2026-10-25 07:19 | eval injection | 10.00 | 0.2154 | 9.7846 | 0.2154 |
| 2026-10-25 07:20 | eval injection | 10.00 | 0.2215 | 9.7785 | 0.2215 |
| 2026-10-25 07:28 | eval cycle 6: answer version, injection set, parser fix (code), conftest [tests: 620 passed, 1 warning; server: 30/30] | 10.00 | 0.2218 | 9.7782 | 0.2218 |
| 2026-10-25 07:34 | eval split store (copy) | 10.00 | 0.2981 | 9.7019 | 0.2981 |
| 2026-10-25 07:42 | eval split store (copy) + repeal notices | 10.00 | 0.3178 | 9.6822 | 0.3178 |
| 2026-10-25 07:59 | eval provider: baidu | 10.00 | 0.3367 | 9.6633 | 0.3367 |
| 2026-10-25 08:00 | eval provider: deepinfra | 10.00 | 0.3500 | 9.6500 | 0.3500 |
| 2026-10-25 08:02 | eval en06 check | 10.00 | 0.3538 | 9.6462 | 0.3538 |
| 2026-10-25 08:04 | eval en06 live baidu | 10.00 | 0.3575 | 9.6425 | 0.3575 |
| 2026-10-25 08:33 | eval cycle 7: re-imported 85 acts (+820 units), repeal notices, provider routing (baidu, fp8, price cap), scope rescue [tests: 633 passed, 1 warning; server: 30/30] | 10.00 | 0.4045 | 9.5955 | 0.4045 |
| 2026-10-25 08:38 | eval cycle 7 (rerun after the DNS outage): re-imported acts, repeal notices, provider routing, scope rescue [tests: 633 passed, 1 warning; server: 30/30] | 10.00 | 0.4245 | 9.5755 | 0.4245 |
| 2026-10-25 08:48 | eval cycle 8: embedding options (off by default), query-embedding path, dense-only probe [tests: 635 passed, 1 warning; server: 30/30] | 10.00 | 0.5853 | 9.4147 | 0.5853 |
| 2026-10-25 12:13 | eval qwen3-embedding-8b@1024 (copy) | 10.00 | 0.6666 | 9.3334 | 0.6666 |
| 2026-10-25 12:18 | eval cycle 9: review fixes (repeal notices strict, no caching after retrieval timeout, rescue only over the lexical gate, Russian document search), hours-as-decimal check [tests: 645 passed, 1 warning; server: 30/30] | 10.00 | 0.6686 | 9.3314 | 0.6686 |
| 2026-10-25 12:34 | eval cycle 10: clean-install check, embedding comparison docs (production unchanged) [tests: 645 passed, 1 warning; server: 30/30] | 10.00 | 0.6705 | 9.3295 | 0.6705 |
| 2026-10-25 12:43 | eval cycle 11: review fixes (exact number words, list-bracket ids, remove-not-move repair, price-cap retry, stricter eval criteria) [tests: 668 passed, 1 warning; server: 30/30] | 10.00 | 0.6705 | 9.3295 | 0.6705 |
| 2026-10-25 13:04 | eval cycle 12: ingestion review fixes (60 Russian points moved to their units, multi-point repeal notes, text-keyed audit cache), 3 cards reopened [tests: 674 passed, 1 warning; server: 30/30] | 10.00 | 0.6899 | 9.3101 | 0.6899 |
| 2026-10-25 13:14 | eval injection set (final) | 10.00 | 0.7091 | 9.2909 | 0.7091 |
| 2026-10-25 13:35 | eval cycle 13 (final state): injection check negation window, 9 misaligned Russian texts of VMQ-319 removed [tests: 678 passed, 1 warning; server: 30/30] | 10.00 | 0.7372 | 9.2628 | 0.7372 |
