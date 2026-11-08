# E36 — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,158 rows |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,744 nodes / 45,455 edges |

## Arms

| Arm | Disabled stage |
|---|---|
| full | none |
| no_expansion | `_expand_query` |
| no_bucket | `apply_bucket_weights` |
| no_cochange | `_apply_co_change_boost` |
| no_p2 | `_anchor_identifier_chunks_async` |
| no_p3 | `_anchor_module_head_chunks_async` |
| no_o1 | `_apply_o1_identifier_boost` |
| no_exact | `_boost_exact_name_matches` |
| no_dedupe | `_dedupe_by_symbol` |
| no_graph | `_graph_stage` |
| minimal | all of the above |

E33 demote ON for every arm. No embeddings, no reranker.
Metrics: hit@1/hit@5/MRR, p50/p95.
