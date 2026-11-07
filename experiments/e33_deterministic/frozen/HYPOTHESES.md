# E33 — frozen hypotheses (before the first run)

Panel: E30 48 real queries, sha `d4934cb7…`. Same SQLite/FTS5 index and graph.
All arms are deterministic: no embeddings, no reranker.

Arms:
- baseline: current fused retrieval (FTS5 weights 1,1,1,1,1)
- fts_weights: FTS5 column weights (text 1, text_full 1, symbol 3, doc 1.5, path 1.5)
- fts_weights_demote: + demote tests/docs/experiments/fixtures (×0.3)
- fts_weights_demote_prior: + caller-count prior + exact-name/path boost

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | FTS5 field weights improve hit@1 by >= 2 queries | delta < 2 queries | PASS |
| H2 | test/doc demotion improves hit@1 by >= 1 query | delta < 1 query | PASS |
| H3 | caller prior + exact-name/path boost improves hit@1 by >= 1 query | delta < 1 query | PASS |
| H4 | all deterministic boosts reach hit@1 >= 0.70 | hit@1 < 0.70 | **FAIL** (deterministic signals alone may not close the gap) |
| H5 | p50 stays < 300 ms | p50 >= 300 ms | PASS |
| H6 | deterministic boosts reach hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** (95% is not realistic on this panel) |

Metrics: hit@1/hit@5 file, MRR file, p50/p95 wall-clock.
