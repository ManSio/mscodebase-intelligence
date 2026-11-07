# E40 — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,347 rows |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,980 nodes |

## Change

`src/core/search/synonyms_ru.py` — curated Russian → English code terms
(`RU_EN`) and phrases (`RU_PHRASES`). Searcher flag `_ru_synonyms`; variants up
to 4, merged by existing RRF. No index change.

## Arms

| Name | RU synonyms |
|---|---|
| baseline | off |
| ru_synonyms | on |

E33 demote ON, P3 off, no reranker. Metrics: hit@1/hit@5/MRR, p50/p95.
