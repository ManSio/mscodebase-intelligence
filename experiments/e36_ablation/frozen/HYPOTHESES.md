# E36 — deterministic pipeline ablation (before the first run)

Panel: E30 48 queries, sha `d4934cb7…`. SQLite/FTS5 16,158 chunks, graph 13,744
nodes. No embeddings, no reranker. E33 demote ON.

Each arm disables one deterministic stage; the full arm is the current pipeline.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | query expansion is a no-op on this Russian panel | disabling changes hit@1 by >= 1 | PASS |
| H2 | bucket weights matter (docs ×0.5) | disabling changes hit@1 by >= 2 | PASS |
| H3 | co-change boost is a no-op (no commit memory / weak signal) | disabling changes hit@1 by >= 1 | PASS |
| H4 | P2 identifier anchors help | disabling reduces hit@5 by >= 2 | PASS |
| H5 | O1/exact-name boosts help identifiers | disabling reduces hit@1 by >= 2 | PASS |
| H6 | P3 module-head anchors are dead in SQLite mode (no `_bm25_df`) | disabling changes hit@1/hit@5 by >= 1 | PASS |
| H7 | full pipeline reaches hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |
| H8 | dedupe changes hit@1 | disabling changes hit@1 by >= 1 | **FAIL** (dedupe should not change top-1) |

Arms: full, no_expansion, no_bucket, no_cochange, no_p2, no_p3, no_o1,
no_exact, no_dedupe, no_graph, minimal.
