# E55 — manifest (frozen before the first run)

| Input | Path / value |
|---|---|
| Queries (48) | `frozen/QUERIES.jsonl`, sha256 `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Index | `.mscodebase/chunks.db` (clean: 7,314 chunks, 0 experiments) |
| Graph | `%LOCALAPPDATA%/mscodebase/projects/bfe9644b/graph.db` (12,753 nodes / 45,762 edges) |
| Flags | dense off, on-demand rerank off, P3 false, demote non-code true (unless arm) |
| Modes | `hybrid_search_async`; `search_with_mode` fast/quality/deep |

## Arms

- `hybrid` — async hybrid baseline.
- `fast`, `quality`, `deep` — real `search_with_mode` paths.
- `quality_nodemote` — `_demote_non_code=False`.
- `quality_intent` — `_demote_intent_aware=True`.
- `quality_ru` — `_ru_synonyms=True`.
- `quality_p3` — `_p3_anchor=True`.

Metrics: hit@1/hit@5 overall + code/docs, p50/p95.
