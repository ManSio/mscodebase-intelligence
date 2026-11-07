# E38 — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,347 rows |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,980 nodes |

## Model

`onnx-community/bge-reranker-base-ONNX` → `onnx/model_int8.onnx` (279 MB),
tokenizer 512, CPUExecutionProvider. Cross-encoder: `(query, passage)` pairs,
logit score, higher = better.

## Arms

| Name | Pool | Rerank |
|---|---:|---|
| demote | top5 | none |
| bge_base_top10 | top10 | BGE-base int8 |
| bge_base_top20 | top20 | BGE-base int8 |

E33 demote ON, P3 off, no stored vectors. Warm-up one query per arm.
