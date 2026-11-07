# E57 — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Index | `.mscodebase/chunks.db` (clean, 7,314 chunks) |
| Graph | production graph (12,753 nodes) |
| Router | `auto_detect_intent` (lexical, no LLM) |
| Code channel | `search_with_mode("quality", limit=5)` |
| Docs channel | `Searcher.search_docs(query, limit=5)` |

## Arms

- `code_only`.
- `auto`: docs channel if `auto_detect_intent == "docs"`, else code.
- `oracle`: docs if gold is docs, else code (upper bound).

Metrics: exact and same-basename hit@1/hit@5, subsets, p50.
