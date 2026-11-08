# E56 — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Index | `.mscodebase/chunks.db` (clean, 7,314 chunks) |
| Code channel | `Searcher.search_with_mode("quality", limit=5)` |
| Docs channel | `SQLiteChunkStore.search(query, limit=1000)` filtered `docs/**` |
| Flags | dense off, on-demand rerank off, demote non-code true |

## Arms

- `code_only` — quality results.
- `docs_only` — docs BM25.
- `oracle` — docs first iff gold is docs, else code (upper bound).
- `code4_docs1` — code top4 + docs top1.
- `docs1_code4` — docs top1 + code top4.

Metrics: hit@1/hit@5/hit@10 overall + code/docs, p50.
