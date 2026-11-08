# E38 — frozen hypotheses (before the first run)

Panel: E30 48 queries, frozen `d4934cb7…`. Corrected index, E33 demote ON,
P3 off, no stored vectors. Reranker: **BGE-reranker-base ONNX int8**
(multilingual XLM-R cross-encoder, 279 MB) over top-10/top-20.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | BGE-base top10 improves hit@1 by >= 2 over demote | delta < 2 | PASS |
| H2 | BGE-base top10 improves hit@5 by >= 1 | delta < 1 | PASS |
| H3 | top20 improves hit@1 over top10 | hit@1(top20) <= hit@1(top10) | **FAIL** (bigger pool adds noise) |
| H4 | p50 < 2000 ms | p50 >= 2000 ms | PASS |
| H5 | hit@1 >= 0.75 | hit@1 < 0.75 | **FAIL** (unknown; 95% far) |
| H6 | hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |
| H7 | BGE-base beats MS MARCO MiniLM (0.417) | BGE-base <= 0.417 | PASS |

Metrics: hit@1/hit@5 file, MRR, p50/p95.
