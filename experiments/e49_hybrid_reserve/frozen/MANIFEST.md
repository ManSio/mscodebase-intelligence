# E49 — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Code graph | `experiments/e46_pagerank_map/results/graph_complete.db` (759 code files) |
| Docs | `chunks.db` via `get_chunks_db_path(ROOT)` (348 docs) |
| BM25 | `SQLiteChunkStore.search(query, limit=100)` |
| RU map | `synonyms_ru.RU_EN` |
| Token reserve | 15% and 25% of budget for docs |

## Arms

- `base`: code PageRank, no BM25 seed.
- `bm25_code`: code files ordered by BM25 only.
- `hybrid_code`: PageRank with BM25 top-code files as seeds (+100).
- `reserve15`: hybrid_code map at 85% budget + top docs map at 15%.
- `reserve25`: hybrid_code map at 75% budget + top docs map at 25%.
- `docs2_code`: top-2 docs prepended to hybrid code order.
- `oracle`: perfect docs/code routing (upper bound).

Metrics: gold coverage 1k/2k/4k, code/docs subsets, p50/p95.
