# E46 — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Graph | `%TEMP%/opencode/mscodebase_symbolfix_backup_20261025_002249/graph.db` | 21,184,512 B; 13,744 nodes |

## Graph build

- Nodes: symbols/files with `file_path`.
- Edges: CALLS, ASSIGNED_FROM, IMPORTS, DECORATES, OVERRIDES; skip DEFINES.
- File graph: source_file → target_file; weight = edge count.
- PageRank: damping 0.85, 30 iterations, dangling handling.
- Personalization: uniform + boost files whose path/symbol name contains a
  content token from the query (Russian stopwords removed).
- Map: ranked files, top symbols per file (by node degree), token estimate
  4 chars/token; stop at budget.

## Arms

| Name | Ranking | Budgets |
|---|---|---|
| degree | in-degree | 1k/2k/4k |
| global | PageRank uniform | 1k/2k/4k |
| personalized | PageRank query bias | 1k/2k/4k |

Metrics: gold-file coverage, map tokens, p50/p95.
