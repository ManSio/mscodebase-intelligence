# E32 — frozen hypotheses (before the first run)

Panel: E30 48 real queries, sha `d4934cb7…`. Same SQLite/FTS5 index
(16,158 chunks) and PropertyGraph. No embeddings, no reranker: only the BM25
arm changes.

Arms:
- baseline: current BM25 (`\W+` tokens, `tf*idf`, no length norm)
- code_b75: code tokenizer + field boosts (name×3, path×2) + proper BM25, b=0.75
- code_b45: same, b=0.45
- code_b45_stop: same + stopwords (default)

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | code BM25 improves hit@1 by >= 2 queries over baseline | delta < 2 queries | PASS |
| H2 | b=0.45 improves hit@5 over b=0.75 | hit@5(b45) <= hit@5(b75) | **FAIL** (b is corpus-dependent) |
| H3 | stopwords improve hit@1 over no-stopwords | hit@1(stop) <= hit@1(no-stop) | **FAIL** (stopwords may drop exact symbol words) |
| H4 | code BM25 p50 within 2× baseline | p50 > 2× baseline | PASS |
| H5 | code BM25 reaches hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** (95% is not realistic on this panel) |

Metrics: hit@1/hit@5 file, MRR file, p50/p95 wall-clock of
`Searcher.hybrid_search_async` with clean fused retrieval (no on-demand rerank,
no BGE).
