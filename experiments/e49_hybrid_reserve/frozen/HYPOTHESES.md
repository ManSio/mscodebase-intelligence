# E49 — frozen hypotheses (before the first run)

**Idea:** E48 showed docs BM25 is strong but keyword routing is brittle.
Remove the classifier: always query docs BM25 and reserve ~15% of the token
budget for top docs. Improve the code channel with BM25 top-files as PageRank
seeds (hybrid). Latency budget raised to 5–10 s; correctness matters more.

Panel: E30 48 queries. No embeddings, no LLM.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | code BM25 1k > base code 1k (0.325) | <= | PASS |
| H2 | hybrid_code 1k >= base + 5 p.p. | < +5 | PASS |
| H3 | reserve15 1k >= 40% (all) | < 40% | PASS |
| H4 | reserve15 docs 1k >= 50% | < 50% | PASS |
| H5 | reserve15 2k >= 65% (all) | < 65% | PASS |
| H6 | reserve15 4k >= 75% (all) | < 75% | PASS |
| H7 | reserve15 4k >= 95% | < 95% | **FAIL** |
| H8 | p50 < 5,000 ms | >= 5,000 | PASS |
| H9 | reserve15 code 1k within 5 p.p. of hybrid_code | > 5 p.p. drop | PASS |

E48 oracle ceiling: 0.396 / 0.625 / 0.729. Docs BM25: 0.75 / 1.00 / 1.00.
