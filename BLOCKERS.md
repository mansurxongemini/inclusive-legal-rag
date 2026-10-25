# BLOCKERS (agent/max-quality run)

Nothing blocks the service. These items need the owner (editorial judgement or a decision), or are known limits.

## 1. 15 open editorial notifications (owner)
Two Lex.uz refreshes on 2026-10-25 (85 re-imported acts in the morning, every registry act in the evening) brought new
text. 39 of the cards they opened were closed automatically, each with a note: re-parse only (no sentence changed), or
`--keep-untouched` (the post names no changed unit and repeats no words around a change; scripts/classify_refresh_changes.py).
These 15 stay open because the post may be affected: VMQ-62 (Chernobyl participants, 6 posts), VMQ-313 (point 10-1, 2),
VMQ-119 (new allowance rules, 2), VMQ-183, VMQ-223, PF-79 (text removed), Law 641 art. 28 ("konstitutsiyaviy" courts added;
post uz:2063 relies on it) and VMQ-405 point 29 (the subsidy deadline moved from the 16th to the 26th; post uz:8594 still
says the 16th). Until resolved in the admin panel (Bildirishnomalar), those posts are kept out of answers.

## 2. 54 units still contain later points (known limit)
`scripts/audit_corpus.py` reports 54 units (171 before the parser fix) whose text holds later point numbers without units
of their own. They are other layouts (quoted amendment lists, tables); the text is present and retrievable, citations are
coarser.

## Resolved on 2026-10-25
- VMQ-240 (2008): Lex.uz has a new edition (one annex instead of two, 32 sentences reworded); the stored text was outdated.
  Re-imported with `--allow-mass-removal` after checking that no gold item, editorial link or post referenced its units.
- Embedding model: the owner approved qwen3-embedding-8b; switched (DECISIONS.md, docs/EMBEDDING_COMPARISON.md).
