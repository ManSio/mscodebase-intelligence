# E44 — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries + rewrites (48) | `frozen/QUERIES_REWRITTEN.jsonl` | `9f87fbb2b2ce9c683d5982f9c643c59cf07b2ecc87ae6e79b0979785818af748` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,347 rows |

## Rewrite generator

Deterministic: original, stopword-stripped keywords, extracted code identifiers,
RU→EN term replacement, concept terms. No model, no gold leakage.

## Arms

| Name | Variants |
|---|---|
| baseline | current `_expand_query` |
| keywords | `rewrites[1]` |
| identifiers | `rewrites[2]` |
| agent_all | all `rewrites` |

E33 demote ON, P3 off, no reranker, no graph stage. Metrics: hit@1/hit@5/MRR, p50/p95.

