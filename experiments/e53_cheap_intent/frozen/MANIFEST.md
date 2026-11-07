# E53 — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Index | `experiments/e52_clean_baseline/results/chunks_clean.db` (7,258 chunks) |
| Search | `Searcher.hybrid_search_async(query, limit=5)` |
| Flags | dense off, on-demand rerank off, demote non-code true, P3 false |
| Arms | `baseline` (`_demote_intent_aware=False`), `intent` (`True`) |

Change under test: Russian docs/architecture signals in `auto_detect_intent`.
Metrics: hit@1/hit@5 overall + code/docs subsets, p50, false-positive docs intent.
