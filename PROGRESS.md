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
- Cycles done: 1-5 (all criteria met from cycle 2; gold v2 from cycle 4: recall@5 0.95). Clean install verified (fresh clone).
- Parser fix for points after a repealed point (ea48892): refreshing the 85 affected acts in a COPY of the store
  (scratchpad/split_store) to compare ids/references and run the gold set on the copy before touching data/store.
- Injection set (eval/injection_set.jsonl): no injected instruction followed.

## Next
- Decide on the split refresh (apply to live only if gold metrics hold and no referenced id disappears), cycles 6-10,
  re-run the clean install on the final commit, FINAL_REPORT.md.

## Notes
- Merged-points data item (171 units) left open: BLOCKERS.md.
- Cost so far ~ $0.21 (BUDGET.md). Stop paid calls at $3.50 spent.
