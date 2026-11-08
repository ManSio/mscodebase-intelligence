# E31 — manifest (frozen before the first run)

## Inputs

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,158 rows / 1,473 files |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,744 nodes / 45,455 edges |

## Models

| Role | Endpoint |
|---|---|
| BGE-M3 cross-encoder reranker | `POST http://127.0.0.1:8081/rerank` |
| No vectors stored | dense off; candidate pool from SQLite FTS5 + BM25 + graph |

## Configs

| Name | Pool | Rerank |
|---|---:|---|
| no_rerank | top5 fused | none |
| bge_top10 | top10 fused | BGE-M3 |
| bge_top30 | top30 fused | BGE-M3 |
| bge_top50 | top50 fused | BGE-M3 |

## Method

- Clean fused retrieval (`Searcher.hybrid_search_async`, `_ondemand_rerank=False`,
  multi-reranker disabled) returns the top-N fused candidates.
- Candidate texts truncated to 2,000 chars before `/rerank` (server input bound).
- Sort by BGE score descending, take top 5.
- Warm-up one query per config, not counted.
- Raw rows: `results/<config>.json`.

## Caveats

- 48 queries, one project, one CPU machine; absolute numbers are directional.
- BGE-M3 is 568M Q4_K_M; p50 is measured on this machine, not a general SLA.
- 95% hit@1 is a stretch target; 95% hit@5 is the more realistic bar.
