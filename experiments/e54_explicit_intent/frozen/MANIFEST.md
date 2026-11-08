# E54 — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Index | `experiments/e52_clean_baseline/results/chunks_clean.db` |
| Search | `Searcher.hybrid_search_async(query, limit=5, intent_hint=<gold-derived>)` |
| Flags | dense off, on-demand rerank off, demote non-code true, demote intent-aware true, P3 false |
| Arms | `baseline` (auto intent), `explicit` (docs/code from gold) |

Explicit intent is the upper bound of what an agent can pass for free; no LLM
router is involved. Metrics: hit@1/hit@5 + subsets, p50.
