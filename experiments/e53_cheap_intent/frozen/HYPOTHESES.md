# E53 — frozen hypotheses (before the first run)

**Idea:** no LLM router (too expensive). Use the existing lexical
`auto_detect_intent`, extended with Russian docs/architecture signals, to stop
demoting docs for docs-intent queries. Clean index (E52), production-like
search, two arms: intent-aware off/on.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | intent-aware docs hit@1 > 0 | 0 | PASS |
| H2 | intent-aware overall hit@1 >= 0.70 | < 0.70 | PASS |
| H3 | code hit@1 not below baseline by > 2 p.p. | < 0.805 | PASS |
| H4 | intent-aware hit@5 >= 0.75 | < 0.75 | PASS |
| H5 | p50 < 5,000 ms | >= 5,000 | PASS |
| H6 | intent-aware hit@1 >= 0.95 | < 0.95 | **FAIL** |
| H7 | intent-aware docs hit@5 > 0 | 0 | PASS |
| H8 | false-positive code queries (docs intent) <= 3 | > 3 | PASS |

Baseline clean production (E52): 0.688/0.750; code 0.825/0.900; docs 0/0.
