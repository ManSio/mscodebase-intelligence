# E35 — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,158 rows |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,744 nodes / 45,455 edges |

## Model

`cross-encoder/ms-marco-MiniLM-L-6-v2` (Xenova ONNX int8, 23 MB), tokenizer 512,
CPUExecutionProvider. No vectors are stored; the model scores (query, passage)
pairs live.

## Arms

| Name | Pool | Rerank |
|---|---:|---|
| demote | top5 | none |
| minilm_top10 | top10 | MiniLM |
| minilm_top20 | top20 | MiniLM |

Metrics: hit@1/hit@5/MRR, p50/p95. Warm-up one query per arm.
