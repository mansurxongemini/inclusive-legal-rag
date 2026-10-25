# BLOCKERS (agent/max-quality run)

Nothing blocks the service. These items need the owner (editorial judgement or a decision), or are known limits.

## 1. 14 open editorial notifications (owner)
The re-import of 85 acts (2026-10-25) brought new text from Lex.uz for VMQ-119 (64 new sentences: allowance rules),
VMQ-313 (point 10-1 inserted), VMQ-62 (a point on Chernobyl participants) and VMQ-482; text was removed from VMQ-183,
VMQ-223 and PF-79. 38 re-parse-only notifications were resolved through the "keep" path (scripts/classify_refresh_changes.py);
these 14 stay open in the admin panel
(Bildirishnomalar). Until they are resolved, the Huquq+ posts linked to those acts are held back from answers
("Dropping hp context ... (open notifications exist)" in the log).

## 2. VMQ-240 (2008) skipped by the refresh (owner / next run)
`refresh` refused to replace it: 34 of 39 stored units would disappear (mass-removal guard). The stored units are kept.
Look at the act on Lex.uz and run `scripts/build_disability_corpus.py refresh --law-ids=vmq_240_2008 --allow-mass-removal`
only if the new parse is right.

## 3. 55 units still contain later points (known limit)
`scripts/audit_corpus.py` reports 55 units (171 before the parser fix) whose text holds later point numbers without units
of their own. They are other layouts (quoted amendment lists, tables); the text is present and retrievable, citations are
coarser.

## 4. Embedding model (owner's decision)
qwen/qwen3-embedding-8b was compared with bge-m3 on a copy of the store (docs/EMBEDDING_COMPARISON.md): dense recall@5
0.707 -> 0.836, whole-path recall@5 0.964 -> 0.971 and MRR 0.921 -> 0.957, same price, same size at 1024 dimensions.
Production stays on bge-m3 until the owner decides (the owner's rule); the switch is one re-embedding (~9 min, ~$0.08), steps in
that document.
