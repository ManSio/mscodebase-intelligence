# E56 — frozen hypotheses (before the first run)

**Idea:** no router. Add a cheap **docs-only FTS channel** (one query, filter
`docs/**`) and test merge policies against the real code channel.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | docs-only hit@1 >= 0.70 | < 0.70 | PASS |
| H2 | oracle route overall hit@1 >= 0.80 | < 0.80 | PASS |
| H3 | oracle route hit@5 >= 0.90 | < 0.90 | PASS |
| H4 | code4+docs1 hit@5 >= code-only + 5 p.p. | < +5 | PASS |
| H5 | docs1+code4 overall hit@1 < 0.30 | >= 0.30 | PASS |
| H6 | p50 < 5,000 ms | >= 5,000 | PASS |
| H7 | best hit@1 >= 0.95 | < 0.95 | **FAIL** |
| H8 | oracle docs hit@1 >= 0.75 | < 0.75 | PASS |
| H9 | oracle code hit@1 unchanged (0.825) | < 0.825 | PASS |

Baseline quality: 0.688/0.771; code 0.825/0.900; docs 0/0.125.
