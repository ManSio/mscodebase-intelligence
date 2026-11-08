# E51b — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Index | `chunks.db` (16,347 chunks) |
| Retrieval filter | exclude `experiments/**` and `.mscodebase/**` |
| Graph | `experiments/e46_pagerank_map/results/graph_complete.db` |
| Search | FTS5 BM25, `limit=500` before filtering |
| Policy | identical to E51 (4 steps, 8k tokens) |

Contamination evidence: E51 `single_top1` was
`experiments/4A_unit_of_return/frozen/f5/queries.md` for most queries; that file
contains the same probes.

Metrics: hit@1, hit@5, code/docs subsets, p50/p95, avg calls/tokens.
