# PROGRESS (agent/max-quality run)

Read this first after a context reset. Branch `agent/max-quality`; never push; never touch .env.

## Done
- Baseline commit 1b53fea; backup `data/backups/legal_rag_backup_20261025_002450` (verified); start balance $10.00.
- Gold set `eval/gold_set.jsonl` (76 items: 26 uz / 25 ru / 25 en), builder `eval/build_gold_set.py`.
- Runner `eval/run_eval.py` (production path, HTTP response cache `eval/cache/llm_cache.sqlite`, reports `eval/reports/`).
- Server check `eval/check_server.py` (idle RSS, /health, bad input, SSE drop, failing provider, leak, secrets): 30/30.
- Fixes (each with tests): guard repairs unknown citation ids; 284 shifted Russian texts removed + importer pairing fix;
  hierarchy (old law numbers, Huquq+ commentary weight); scope covers all Law-641 rights; number words in the
  ungrounded-number check; retrieval deadline with model-free fallback; no emoji in answers/admin API/logs; document
  search 90 s -> 0.6 s; conftest import order; live test moved to gold item uz26.
- Admin panel (/admin-v2 -> /admin, 7 sections) checked in the browser on a store copy: no console errors, all 200.
- Eval: baseline recall@5 0.891 / cit 95.5% / false refusal 2.9% -> cycle 2 recall@5 0.921, all gold criteria met.

## Now
- Regression cycles (need >= 10 after baseline; done: 1, 2). Each: full pytest, gold set (cache), server check.

## Next
- Clean install per README in a fresh venv/dir; FINAL_REPORT.md.

## Notes
- Merged-points data item (171 units) left open: BLOCKERS.md.
- Cost so far ~ $0.21 (BUDGET.md). Stop paid calls at $3.50 spent.
