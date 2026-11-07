# E42 — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,347 rows |

## Change

`demote_intent_aware`: `auto_detect_intent(query)`; if `docs`, demote only
tests/test/experiments/fixtures (not docs/); otherwise demote all non-code.

## Arms

| Name | Demote |
|---|---|
| baseline | all non-code |
| intent_aware | docs-intent keeps docs |

P3 off, no reranker. Metrics: hit@1/hit@5/MRR, p50/p95, docs/code subset.
