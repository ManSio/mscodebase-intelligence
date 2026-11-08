# E41 — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Base SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,347 rows |

## Change

Temporary SQLite/FTS5 store with every `file_path` starting with `experiments/`
removed (query panels, frozen answers, run artifacts). Same E33 demote, P3 off,
no reranker, no graph stage.

## Arms

| Name | Store |
|---|---|
| baseline | current store (with experiments) |
| no_experiments | filtered store |

Metrics: hit@1/hit@5/MRR, p50/p95.
