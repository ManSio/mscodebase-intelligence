# E51 — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Index | `chunks.db` via `get_chunks_db_path(ROOT)` (16,347 chunks) |
| Graph | `experiments/e46_pagerank_map/results/graph_complete.db` (9,315 nodes / 47,286 edges / 759 files) |
| Search | `SQLiteChunkStore.search(query, limit=200)` (FTS5 BM25) |
| Graph expand | file-level neighbours from CALLS/ASSIGNED_FROM/IMPORTS/DECORATES/OVERRIDES |
| Token budget | 8,000 context tokens (read text / 4) |
| Max steps | 4 |

## Policy

- Step 1: search original query (200), take top files.
- Step 2: read top-3 chunks, extract identifiers, search `query + top identifiers`.
- Step 3: add graph neighbours of top-5 files.
- Step 4: RRF over steps + symbol overlap + graph proximity; return top-5 files.

Metrics: hit@1, hit@5, code/docs subsets, p50/p95, avg tool calls, avg tokens.
