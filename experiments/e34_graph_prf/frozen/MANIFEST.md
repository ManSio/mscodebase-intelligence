# E34 — manifest (frozen before the first run)

## Inputs

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,158 rows / 1,473 files |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,744 nodes / 45,455 edges |

## Arms

| Name | PRF | Graph |
|---|---|---|
| demote | no | no |
| demote_prf | top-1 symbol | no |
| demote_graph | no | callers/callees of top-3 |
| demote_graph_prf | top-1 symbol | callers/callees of top-3 |

## Method

- Pool = top-30 fused results, demote non-code ON.
- PRF: `store.search(query + " " + top1.symbol_name)`, take top-10, add with
  score = top1_score × 0.8.
- Graph: `symbol_index.build_call_graph(sym, depth=1)` for top-3; for each
  caller/callee, `store.get_symbol_chunk(file, symbol)`; add with
  score = top1_score × 0.6.
- Dedup by file:chunk_index, sort by score, take top 5.
- Warm-up one query per arm, not counted.
- Raw rows: `results/<arm>.json`.

## Caveats

- 48 queries, one project, one CPU machine; directional, not an SLA.
- PRF/graph candidates are appended with a fixed bonus; this is a deterministic
  heuristic, not a learned ranker.
