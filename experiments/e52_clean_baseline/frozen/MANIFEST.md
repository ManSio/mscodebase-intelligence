# E52 — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Source index | `.mscodebase/chunks.db` (16,347 chunks) |
| Clean index | `results/chunks_clean.db` (copy without `experiments/**`, `.mscodebase/**`) |
| BM25 | `SQLiteChunkStore.search(query, limit=1000)` |
| Production-like | `Searcher.hybrid_search_async(query, limit=5)`; dense off, on-demand rerank off, demote non-code true, P3 false |
| Leakage probe | `experiments/4A_unit_of_return/frozen/f5/queries.md` |

Metrics: hit@1/hit@5 for BM25 and production, contaminated vs clean, p50,
removed chunk count, leakage presence.
