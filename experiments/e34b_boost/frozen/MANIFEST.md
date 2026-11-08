# E34b — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,158 rows |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,744 nodes / 45,455 edges |

Arms: demote (baseline), graph_x15 (graph candidates ×1.5 top-1),
prf_x12 (PRF ×1.2 top-1), both_x15 (both). No embeddings, no reranker.
Metrics: hit@1/hit@5/MRR, p50/p95.
