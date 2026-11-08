# E43 — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,347 rows |

## Concept lexicon

15 groups: auth, cache, database, config, error, rate_limit, graph, search,
index, memory, concurrency, network, file, test, process, security. Each group
has RU/EN terms; tags are counted from `symbol_name + file_path + text`.

## Method

- Build `concept -> [chunk]` with deterministic term counts, top 20 per concept.
- For a query, find matched concepts; append their chunks with score =
  top1_score × factor; dedup by file:chunk_index; sort; take top5.
- Baseline uses the same fused top30 without concept candidates.
- Metrics: hit@1/hit@5/MRR, p50; concept vs non-concept subset.
