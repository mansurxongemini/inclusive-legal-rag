# DECISIONS (agent/max-quality run)

Format: what - why - how to undo.

- 2026-10-25 Committed the previous sessions' uncommitted work as the first commit of `agent/max-quality` - my changes must be reviewable as small commits on top of it - `git reset --soft 40c4185` on this branch.
- 2026-10-25 Gold set expected units are written as slots of acceptable ids (e.g. home examination: law 641 art. 31 or Regulation 62 item 16) - several units of the corpus state the same rule; one id per question would punish a correct retrieval - edit `eval/build_gold_set.py`.
- 2026-10-25 No "repealed" units exist in the corpus (all 27,854 are status=active; current Lex.uz editions omit repealed points). Repealed-norm traps therefore name a repealed act and require the answer to say it lost force - see `trap_repealed` items.
