# PROGRESS (agent/max-quality run)

Read this first after a context reset. Branch `agent/max-quality`; never push; never touch .env.

## State: finished (2026-10-25)
All readiness criteria are met; proof and numbers are in FINAL_REPORT.md. Nothing is running.

- Gold set `eval/gold_set.jsonl` (76: 26 uz / 25 ru / 25 en), runner `eval/run_eval.py` (cached responses, `--offline`),
  server check `eval/check_server.py` (30 checks), injection set `eval/injection_set.jsonl`, regression cycle
  `eval/cycle.sh`, clean install `eval/clean_install.sh`.
- 13 regression cycles in EVAL_HISTORY.md (cycle 7 hit a DNS outage: INVALID, re-run). Baseline recall@5 0.891 ->
  final 0.964; citations 95.5% -> 100%; false refusal 2.9% -> 0%.
- Data: 284 + 9 misaligned Russian texts removed, 60 moved; 85 acts re-imported (+820 units); 3 broken characters and
  18 glued headings fixed. Backups in data/backups/ (each named in DECISIONS.md).
- Admin panel checked in the browser at dce19fa on a store copy (7 sections, all 200, no console errors).
- Clean install OK at dce19fa. Spend ~$0.7 of $4 (BUDGET.md).

## Open for the owner (BLOCKERS.md)
14 editorial cards, VMQ-240 refresh, 55 coarse units, embedding switch decision (docs/EMBEDDING_COMPARISON.md).
