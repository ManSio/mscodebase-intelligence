# E43 — frozen hypotheses (before the first run)

**Idea:** tag each chunk with domain concepts (auth, cache, database, error,
rate_limit, graph, search, index, memory, concurrency, network, file, test,
process, security) from symbol/file/text terms; when a query mentions a concept,
add the concept's tagged chunks to the candidate pool.

Panel: E30 48 queries, corrected index, E33 demote ON, P3 off, no reranker.

Arms:
- baseline: fused retrieval top30
- concept_09: + concept candidates at 0.9 × top1 score
- concept_11: + concept candidates at 1.1 × top1 score

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | concept expansion improves hit@1 by >= 2 | delta < 2 | PASS |
| H2 | concept expansion improves hit@5 by >= 2 | delta < 2 | PASS |
| H3 | non-concept queries do not lose hit@1 | non-concept hit@1 lower | PASS |
| H4 | best concept arm reaches hit@1 >= 0.75 | hit@1 < 0.75 | **FAIL** |
| H5 | best concept arm reaches hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |

Concept tags are built deterministically from the current chunks; no models.
