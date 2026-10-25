# EVAL_HISTORY

Gold set: eval/gold_set.jsonl. Columns: recall@5, MRR, valid citations %, invented articles/ungrounded numbers, honest refusal %, false refusal %, answer language %, key facts %, repealed references, p50 latency (ms, live estimate), new spend (USD), all criteria met.

| when | label | n | recall@5 | MRR | cit.valid | invented | refusal ok | false refusal | lang ok | facts | repealed | p50 ms | spend $ | all met |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-25T00:39 | baseline | 75 | 0.891 | 0.813 | 95.5 | 0/1 | 100.0 | 2.9 | 100.0 | 100.0 | 0 | 13456 | 0.10111 | no |
| 2026-10-25T01:09 | cycle 1: guard ids, ru alignment, hierarchy, scope | 76 | 0.921 | 0.856 | 100.0 | 0/1 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 14772 | 0.047 | no |
| 2026-10-25T01:23 | cycle 2: number words, retrieval deadline | 76 | 0.921 | 0.856 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 16481 | 0.00185 | yes |
| 2026-10-25T07:06 | cycle 3: emoji-free answers, one-pass document search [tests: 612 passed, 1 warning; server: 30/30] | 76 | 0.921 | 0.856 | 100.0 | 0/0 | 100.0 | 0.0 | 100.0 | 100.0 | 0 | 17091 | 0.00082 | yes |
