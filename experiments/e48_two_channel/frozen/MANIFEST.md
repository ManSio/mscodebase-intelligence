# E48 — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Code graph | `experiments/e46_pagerank_map/results/graph_complete.db` (9,315 nodes / 47,286 edges / 759 files) |
| Docs text | `src.core.indexing.chunk_store.get_chunks_db_path(ROOT)` (348 docs) |
| RU map | `src.core.search.synonyms_ru.RU_EN` |
| BM25 | `SQLiteChunkStore.search(query, limit=50)` |
| Routing hints | `docs, readme, докум, архитектур, architecture, design, benchmark, roadmap, audit, report, guide, инструкц, план, spec, adr` |

## Arms

- `base`: code-only personalized PageRank.
- `bm25_docs`: docs BM25 order only.
- `route`: docs order first if query matches hints, else code order first.
- `split75`: 75% budget code map + 25% budget docs map.
- `split50`: 50% / 50%.
- `interleave`: alternate code/docs files.
- `oracle`: docs first iff gold is docs (upper bound, not implementable).

Metrics: gold coverage at 1k/2k/4k, code/docs subsets, p50/p95.
