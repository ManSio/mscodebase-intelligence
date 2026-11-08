# E45 — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Plans (48) | `frozen/PLANS.jsonl` | `093003f4ed3f01330e946d5180e4da3133d0ee081f277a9ab3e08f319c13463c` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,347 rows |

## Plan fields

- `primary`: stopword-stripped keyword query.
- `must_include`: exact code-like tokens extracted from the query (≤5).
- `symbols`: exact symbol-shaped tokens from `must_include` (≤5).

## Arms

| Name | Query | Boosts |
|---|---|---|
| baseline | original + current expansion | none |
| plan_primary | primary, `expand=False` | none |
| plan_must | primary | `must_include` ×2 |
| plan_symbols | primary | exact `symbols` ×2 |
| plan_full | primary | both ×2 |

Demote ON, P3 off, no reranker, no graph. Metrics: hit@1/hit@5/MRR, p50/p95.
