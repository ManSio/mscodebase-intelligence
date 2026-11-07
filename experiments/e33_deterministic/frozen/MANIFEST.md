# E33 — manifest (frozen before the first run)

## Inputs

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,158 rows / 1,473 files |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,744 nodes / 45,455 edges |

## Arms

| Name | FTS5 weights | Demote | Prior |
|---|---|---|---|
| baseline | none | no | no |
| fts_weights | symbol 3 / doc 1.5 / path 1.5 | no | no |
| fts_weights_demote | same | tests/docs/experiments/fixtures ×0.3 | no |
| fts_weights_demote_prior | same | same | callers + exact-name + path |

## Method

- One Searcher per arm, clean fused retrieval (`_ondemand_rerank=False`,
  multi-reranker disabled), pool=30.
- Post-processing is deterministic: score = fused `final_score` × demote ×
  caller prior × exact-name/path boost; stable sort; take top 5.
- Warm-up one query per arm, not counted.
- Raw rows: `results/<arm>.json`.

## Caveats

- 48 queries, one project, one CPU machine; directional, not an SLA.
- FTS5 column order: text, text_full, symbol_name, docstring, file_path.
- The caller prior uses `SymbolIndexAdapter.get_callers` (PropertyGraph).
