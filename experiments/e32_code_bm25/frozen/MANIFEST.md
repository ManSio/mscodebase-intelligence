# E32 — manifest (frozen before the first run)

## Inputs

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,158 rows / 1,473 files |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,744 nodes / 45,455 edges |

## Arms

| Name | code_bm25 | b | stopwords |
|---|---|---|---|
| baseline | false | — | — |
| code_b75 | true | 0.75 | false |
| code_b45 | true | 0.45 | false |
| code_b45_stop | true | 0.45 | true |

`k1=1.2` for all code arms. Field boosts: symbol_name ×3, file_path ×2,
body ×1. No embeddings, no reranker.

## Method

- One Searcher per arm; clean fused retrieval (`_ondemand_rerank=False`,
  multi-reranker disabled).
- Warm-up one query per arm (not counted).
- Metrics: hit@1/hit@5 file, MRR file, p50/p95/mean wall-clock.
- Raw rows: `results/<arm>.json`.

## Caveats

- 48 queries, one project, one CPU machine; directional, not an SLA.
- Only the BM25 arm changes; FTS5/graph are unchanged.
- The code tokenizer emits the raw identifier plus camel/snake/digit subwords.
