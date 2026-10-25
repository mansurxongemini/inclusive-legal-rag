# PROGRESS (agent/max-quality run)

Read this first after a context reset. Branch `agent/max-quality`; never push; never touch .env.

## State: finished (2026-10-25, second round)
All readiness criteria are met; proof and numbers are in FINAL_REPORT.md. Nothing is running.

Second round (owner: quality first, then low cost; switch to qwen3 if it really is better; remove excess code; every act
complete and current, an old rule never shown as current):
- Embeddings: qwen/qwen3-embedding-8b at 1024 dimensions (gold MRR 0.921 -> 0.964-0.971); the store records its model
  (data/store/embedding_model.json) and never mixes two; semantic-cache and gate thresholds re-checked.
- Corpus: every registry act re-read from Lex.uz (534 acts, all in force, 36 with new text), 5 acts added after a new
  discovery run, VMQ-240 current edition; 29 418 units, 38 858 vectors. Corpus and translation audits clean.
- Old law: repealed units never reach the answer; cached answers and articles do not outlive a corpus change.
- Excess code removed (legacy upload/URL ingestion, one-off scripts, old eval harness): 678 -> 628 tests, then new tests.
- Held-out set (95 questions written by another process): 77% of answered in-scope questions correct, 100% of
  out-of-scope refused, 13% of in-scope refused (several outside the service's mission).
- Backups: data/backups/legal_rag_backup_20261025_194616 (before the swap), store_before_qwen_20261025.

## Open for the owner (BLOCKERS.md)
15 editorial cards; 54 coarse units.
