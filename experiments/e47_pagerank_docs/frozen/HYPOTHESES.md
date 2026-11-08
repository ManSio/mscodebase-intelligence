# E47 — frozen hypotheses (before the first run)

**Idea:** E46/E46b personalized PageRank over code files only. Add:
1. docs/README files as graph nodes, linked to code files by symbol mentions;
2. BM25 top-files as a personalization seed;
3. RU→EN query expansion (from E46b).

Same E30 48-query panel. No embeddings, no LLM.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | docs nodes lift docs-gold 1k coverage from 0 to >= 50% | < 50% | PASS |
| H2 | BM25 seed lifts code-only 1k by >= 10 p.p. vs docs arm | < 10 p.p. | PASS |
| H3 | best arm 1k coverage >= 50% (all 48) | < 50% | PASS |
| H4 | best arm 2k coverage >= 70% | < 70% | PASS |
| H5 | best arm 4k coverage >= 95% | < 95% | **FAIL** |
| H6 | p50 < 500 ms | >= 500 ms | PASS |
| H7 | BM25-only 1k > PageRank 1k | <= | **FAIL** (expected) |

E46b baseline (code-only): 0.325 / 0.550 / 0.675 at 1k/2k/4k; docs 0.
