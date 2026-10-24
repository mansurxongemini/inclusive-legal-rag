# BUDGET (agent/max-quality run)

Limits: spend at most $4.00; stop paid calls at $3.50 spent; balance must never fall below $6.00.
Production model unchanged: chat `deepseek/deepseek-v4-flash-0731`, embeddings `baai/bge-m3`.

| When | Event | total_credits | total_usage | balance | spent this run |
|---|---|---|---|---|---|
| 2026-10-25 00:27 | start (GET /api/v1/credits) | 10.00 | 0.00 | 10.00 | 0.00 |
| 2026-10-25 00:34 | eval 20261025_003407 | 10.00 | 0.0001 | 9.9999 | 0.0001 |
| 2026-10-25 00:39 | eval baseline | 10.00 | 0.1086 | 9.8914 | 0.1086 |
| 2026-10-25 01:09 | eval cycle 1: guard ids, ru alignment, hierarchy, scope | 10.00 | 0.1960 | 9.8040 | 0.1960 |
