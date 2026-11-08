# E47 — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Code graph | `experiments/e46_pagerank_map/results/graph_complete.db` (9,315 nodes / 47,286 edges / 759 files) |
| Chunks / docs text | `src.core.indexing.chunk_store.get_chunks_db_path(ROOT)` |
| Docs selection | file path starts `docs/` or ends `.md/.txt/.rst` |
| RU map | `src.core.search.synonyms_ru.RU_EN` |
| BM25 seed | `SQLiteChunkStore.search(query, limit=20)` |

## Arms

- `base`: E46b personalized PageRank, code files only.
- `docs`: + docs files, doc token index, doc→code symbol-mention edges.
- `docs_bm25`: docs + BM25 top-20 files as personalization seeds (+50).
- `bm25`: rank files by BM25 score only.

Metrics: gold-file coverage at 1k/2k/4k, code/docs subsets, p50/p95.
