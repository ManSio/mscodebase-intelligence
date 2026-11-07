# E48 — frozen hypotheses (before the first run)

**Idea:** E47 proved docs must not join the code PageRank graph. Use two
independent channels and merge outside PageRank:
- code: one personalized PageRank over 759 code files (E46b);
- docs: separate BM25 over 348 docs;
- merge by query routing / budget split / interleave.

Panel: E30 48 queries. No embeddings, no LLM.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | route 1k >= base 1k + 5 p.p. (base = 0.271) | < +5 p.p. | PASS |
| H2 | route 1k >= 40% | < 40% | PASS |
| H3 | best arm 1k >= 40% | < 40% | PASS |
| H4 | best arm 2k >= 55% | < 55% | PASS |
| H5 | best arm 4k >= 95% | < 95% | **FAIL** |
| H6 | p50 < 500 ms (one PageRank + one BM25) | >= 500 ms | PASS |
| H7 | oracle 1k >= 40% (upper bound) | < 40% | PASS |
| H8 | docs queries 1k >= 50% (route) | < 50% | **FAIL**? |

E47 numbers: docs dilution 1k=0.042; base 0.271; BM25 docs-only 0.375.
