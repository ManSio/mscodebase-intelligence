# E46b — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Graph | `experiments/e46_pagerank_map/results/graph_complete.db` | 9,315 nodes / 47,286 edges / 759 files |

## Change vs E46

Before PageRank personalization, each Russian query token is expanded through
`synonyms_ru.RU_EN` (e.g. `кэш → cache`, `ошибка → error`). English terms use the
same file/symbol token index. No other change.

Metrics: gold-file coverage at 1k/2k/4k, p50/p95.
