# BLOCKERS (agent/max-quality run)

## Open data item (not blocking): units that swallowed later points
171 units contain later point numbers whose own units do not exist (e.g. `vmq_62_2022_a9_p_44` holds points 44, 46, 47, 48;
`vmq_486_2022_a2_p_10` holds 10 and 12-23). The text is present and retrievable; citations are coarser. Re-import from
Lex.uz with a parser fix is the proper repair (src/ingestion/lex_structured.py); a regex split of stored text was judged
too risky. Detection snippet: see PROGRESS.md "merged points".
