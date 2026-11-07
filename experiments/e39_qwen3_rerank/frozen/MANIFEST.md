# E39 pilot — manifest (frozen before the first run)

| Input | Path | sha256 |
|---|---|---|
| Pilot queries (16) | `frozen/QUERIES_PILOT.jsonl` | `3a8e65819c351f65df32009ed8d1d4699ffeced1131e980cea643e22c934e95b` |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,347 rows |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,980 nodes |

## Model

`shawnw3i/Qwen3-Reranker-0.6B-seq-cls-ONNX` (1.19 GB, fp16), CPUExecutionProvider.
Prompt format: model-card PREFIX/SUFFIX + `<Instruct>: <code retrieval>` +
`<Query>: ...` + `<Document>: ...`; left padding with `<|endoftext|>` id 151643;
max length 2048; score = sigmoid(logit).

## Arms

| Name | Pool | Rerank |
|---|---:|---|
| demote | top5 | none |
| qwen3_top10 | top10 | Qwen3-Reranker-0.6B |
| qwen3_top20 | top20 | Qwen3-Reranker-0.6B |

E33 demote ON, P3 off, no stored vectors. Warm-up one query per arm.
