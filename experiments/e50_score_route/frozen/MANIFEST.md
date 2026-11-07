# E50 — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Code graph | `experiments/e46_pagerank_map/results/graph_complete.db` (759 files) |
| Docs | `chunks.db` via `get_chunks_db_path(ROOT)` (348 docs) |
| BM25 | `SQLiteChunkStore.search(query, limit=100)` |
| Router signal | `max(-final_score)` per channel (top doc vs top code) |
| Thresholds | 0.8, 1.0, 1.2, 1.5, 2.0 |
| Held-out | odd query IDs for threshold choice, even IDs for evaluation |

## Arms

- `base`: code PageRank.
- `docs`: docs BM25 only.
- `oracle`: perfect route (upper bound).
- `route@t`: docs order first if `doc_rel > t * code_rel`, else code first.

Metrics: gold coverage 1k/2k/4k, code/docs subsets, routed docs count, p50.
