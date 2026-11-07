# E37 — frozen hypotheses (before the first run)

Panel: E30 48 queries, sha `d4934cb7…`. Same source, same graph. Chunking is
simulated by splitting existing chunk text into line windows (25% overlap) and
building temporary SQLite/FTS5 stores. No embeddings, no reranker, P3 off,
E33 demote ON.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | 64-line chunks improve hit@5 by >= 2 over current | delta < 2 | PASS |
| H2 | 32-line chunks improve hit@1 by >= 2 over current | delta < 2 | PASS |
| H3 | 128-line chunks are within 1 query of current | delta >= 2 | PASS |
| H4 | best chunk size reaches hit@1 >= 0.75 | hit@1 < 0.75 | **FAIL** |
| H5 | p50 < 300 ms for every arm | p50 >= 300 ms | PASS |
| H6 | best chunk size reaches hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |

Caveat: splitting already-parsed chunk text is an approximation of AST-aware
re-chunking; it preserves the original chunk boundaries but tests line granularity.
