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
