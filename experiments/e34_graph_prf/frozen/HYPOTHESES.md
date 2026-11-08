# E34 — frozen hypotheses (before the first run)

Panel: E30 48 queries, sha `d4934cb7…`. Same SQLite/FTS5 index and graph.
All arms deterministic: no embeddings, no reranker. E33 demote non-code is ON
for every arm.

Arms:
- demote (E33 winner)
- demote_prf: PRF from the top-1 symbol (re-query FTS5/BM25)
- demote_graph: callers/callees of top-3 symbols added to the pool
- demote_graph_prf: both

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | PRF improves hit@1 by >= 2 queries over demote | delta < 2 queries | PASS |
| H2 | graph expansion improves hit@5 by >= 2 queries | delta < 2 queries | PASS |
| H3 | graph+PRF improves hit@1 by >= 3 queries | delta < 3 queries | PASS |
| H4 | graph+PRF reaches hit@1 >= 0.75 | hit@1 < 0.75 | **FAIL** (deterministic recall may not close the gap) |
| H5 | p50 stays < 300 ms | p50 >= 300 ms | PASS |
| H6 | graph+PRF reaches hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** (95% is not realistic on this panel) |
| H7 | graph expansion alone improves hit@1 by >= 1 query | delta < 1 query | **FAIL** (callers/callees are often noise for hit@1) |

Metrics: hit@1/hit@5 file, MRR file, p50/p95 wall-clock.
