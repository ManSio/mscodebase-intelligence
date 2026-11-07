# E30 — frozen hypotheses (before the first run)

Panel: 48 real MSCodeBase queries.
- 33 from `experiments/e28_denseoff/frozen/queries.jsonl` (NL, gold_file).
- 15 fresh docstring-derived queries (`QUERIES_FRESH.jsonl`), frozen before any search run.

Environment: SQLite/FTS5 text index (16,158 chunks, 1,473 files), PropertyGraph
(13,744 nodes / 45,455 edges), DENSE_OFF=true, on-demand rerank.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | Q4 768 top10 hit@1 is within 1 query of Q8 768 top10 (quantization is nearly free) | Q8 hit@1 - Q4 hit@1 >= 2 queries | PASS |
| H2 | Q8 MRL 256 keeps hit@1 within 2 queries of Q8 768 | 768 hit@1 - 256 hit@1 >= 3 queries | PASS |
| H3 | Q4 top20 improves hit@5 by >= 1 query over top10 | hit@5(top20) <= hit@5(top10) | PASS |
| H4 | Q8 768 top10 end-to-end p50 < 600 ms | p50 >= 600 ms | **FAIL** (E18: Q8 embed alone ~2.5 s for 11 texts) |
| H5 | e5 p50 is at least 2x faster than Q8 768 top10 | e5 p50 > 0.5 * Q8 p50 | PASS |
| H6 | cap800 preserves Q8 hit@1 within 1 query of no-cap | hit@1(no-cap) - hit@1(cap800) >= 2 queries | **FAIL** (code context is lost at 800 chars) |
| H7 | no-rerank hit@1 <= Q8 hit@1 (rerank adds quality) | no-rerank hit@1 > Q8 hit@1 | PASS |
| H8 | Q4 768 top10 p50 is within 20% of e5 | Q4 p50 > 1.2 * e5 p50 | **FAIL** (4.4x slower in E18) |

Rules: query set is frozen by sha256 before the run (`MANIFEST.md`); no query is
added/removed after seeing a result. Metrics: hit@1/hit@5 file, MRR file, p50/p95
wall-clock of `Searcher.hybrid_search_async` (SQLite FTS5 + BM25 + graph + rerank).
