# PROGRESS (agent/max-quality run)

Read this first after a context reset.

## Done
- 2026-10-25: branch `agent/max-quality` created; previous uncommitted work committed as baseline (1b53fea).
- Backup: `data/backups/legal_rag_backup_20261025_002450` (all SQLite ok, 37464 vectors).
- OpenRouter balance at start: $10.00 (usage $0). See BUDGET.md.
- Gold set: `eval/gold_set.jsonl` (75 questions: 25 uz / 25 ru / 25 en), built by `eval/build_gold_set.py`, every expected id verified in the store.

## Now
- Writing `eval/run_eval.py` (production path, HTTP-level LLM cache, metrics).

## Next
- Baseline run, then audit (ingest, retrieval, generation, validator, API, security, resources, /admin-v2), regression cycles, clean install, final report.
