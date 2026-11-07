# E37 — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Base SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,347 rows |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,980 nodes |

## Arms

| Name | Lines per chunk |
|---|---:|
| current | original file |
| split32 | 32 |
| split64 | 64 |
| split128 | 128 |

Split windows use 25% overlap. Temporary stores live in `results/` (gitignored
by `experiments/` rules if needed) and are deleted after the run.

## Method

- Each split arm builds a temporary SQLite/FTS5 store from the current chunks.
- Searcher uses that store via `MSCODEBASE_CHUNKS_DB`; graph stage disabled
  (`_symbol_index=None`) to isolate chunking.
- E33 demote ON, P3 off, no embeddings, no reranker.
- Metrics: hit@1/hit@5/MRR, p50/p95.
