# E35 — frozen hypotheses (before the first run)

Panel: E30 48 queries, sha `d4934cb7…`. Same SQLite/FTS5 index and graph.
E33 demote ON. No stored embeddings: the reranker is a small ONNX cross-encoder
(`cross-encoder/ms-marco-MiniLM-L-6-v2`, int8, 23 MB) over the top-N fused pool.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | MiniLM top10 improves hit@1 by >= 2 over demote | delta < 2 | PASS |
| H2 | MiniLM top10 improves hit@5 by >= 1 over demote | delta < 1 | PASS |
| H3 | MiniLM top20 improves hit@1 over top10 | hit@1(top20) <= hit@1(top10) | **FAIL** (bigger pool adds noise) |
| H4 | MiniLM p50 < 1000 ms | p50 >= 1000 ms | PASS |
| H5 | MiniLM reaches hit@1 >= 0.75 | hit@1 < 0.75 | **FAIL** (unknown; 95% is far) |
| H6 | MiniLM reaches hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |
| H7 | MiniLM beats BGE-M3 top10 hit@1 (0.646) | MiniLM <= 0.646 | PASS |

Metrics: hit@1/hit@5 file, MRR file, p50/p95 wall-clock (retrieval + ONNX rerank).
