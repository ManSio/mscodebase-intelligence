# E31 — frozen hypotheses (before the first run)

Panel: the E30 48 real MSCodeBase queries (33 E28 + 15 fresh), sha
`d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac`.
Same SQLite/FTS5 index (16,158 chunks) and PropertyGraph as E30.

Question: does a **cross-encoder rerank (BGE-M3)** over fused lexical/graph
candidates beat the fused ranking — without storing any vectors?

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | BGE top30 improves hit@1 by >= 2 queries over no-rerank | delta < 2 queries | PASS |
| H2 | BGE top30 improves hit@5 by >= 1 query over no-rerank | delta < 1 query | PASS |
| H3 | BGE top30 p50 < 2000 ms | p50 >= 2000 ms | PASS |
| H4 | BGE top50 improves hit@1 over top30 | hit@1(top50) <= hit@1(top30) | **FAIL** (candidate pool is already the bottleneck, not the reranker) |
| H5 | BGE reaches hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** (95% hit@1 is not realistic on this mixed panel) |
| H6 | BGE beats cosine embeddinggemma-2 Q8 (E30: 0.604 hit@1) | BGE <= 0.604 | PASS |
| H7 | BGE top10 equals top30 on hit@1 | delta >= 2 queries | **FAIL** (a truncated pool loses candidates) |

Metrics: hit@1/hit@5 file, MRR file, p50/p95 wall-clock (retrieval + BGE rerank).
Controls: clean fused retrieval (no rerank), BGE top10/top30/top50.
