# E30 — manifest (frozen before the first run)

## Inputs

| Input | Path | Size / sha256 |
|---|---|---|
| Queries (48) | `frozen/QUERIES.jsonl` | `d4934cb7875bd239745fd935dcdef4a6e3e206781b400303c677505de56d9fac` |
| Fresh queries (15) | `frozen/QUERIES_FRESH.jsonl` | generated deterministically from docstrings, frozen before run |
| SQLite chunks | `<project>/.mscodebase/chunks.db` | 16,158 rows / 1,473 files |
| PropertyGraph | `<data_root>/projects/<hash>/graph.db` | 13,744 nodes / 45,455 edges |

## Models (llama.cpp, CPU, Q8/Q4)

| Role | Model | Size | Port |
|---|---|---:|---:|
| embeddinggemma-2 Q8_0 | `models/embeddinggemma-2-Q8_0.gguf` | 309,855,456 | 8080 |
| embeddinggemma-2 UD-Q4_K_XL | `%TEMP%/opencode/models/embeddinggemma-2-UD-Q4_K_XL.gguf` | 175,673,856 | 8085 |
| multilingual-e5-small Q8_0 (control) | `models/multilingual-e5-small-Q8_0.gguf` | 131,953,504 | 8084 |

## Config matrix

| Name | Model | dim | top_n | max_chars | rerank |
|---|---|---:|---:|---:|---|
| e5_384_top10 | e5 | 384 | 10 | 0 | yes |
| q8_768_top10 | Q8 | 768 | 10 | 0 | yes |
| q8_768_top20 | Q8 | 768 | 20 | 0 | yes |
| q8_256_top10 | Q8 (MRL trunc + renorm) | 256 | 10 | 0 | yes |
| q8_768_top10_cap800 | Q8 | 768 | 10 | 800 | yes |
| q4_768_top10 | Q4 | 768 | 10 | 0 | yes |
| q4_768_top20 | Q4 | 768 | 20 | 0 | yes |
| q4_256_top10 | Q4 (MRL trunc + renorm) | 256 | 10 | 0 | yes |
| no_rerank | — | — | — | — | no |

## Method

- One Searcher per config, real `PropertyGraph`, real SQLite FTS5 + BM25.
- The embedder is an HTTP client to the model server with token-trim to 400
  tokens (same idea as `RemoteEmbedder`), then MRL truncation + L2 renorm if dim<full.
- Warm-up call per config is not counted.
- Metrics: hit@1/hit@5 file, MRR file, p50/p95/mean wall-clock of
  `Searcher.hybrid_search_async`, error count.
- Raw rows: `results/<config>.json`.

## Caveats

- 48 queries, one project, one machine; absolute numbers are not production SLA.
- Q4 is `unsloth/embeddinggemma-2-GGUF` UD-Q4_K_XL; Q8 is `ggml-org`.
- CPU only (`-ngl 0`); no GPU.
- The panel includes 33 queries already used in E28. Those are a known-case
  confirmation, not a fresh generalization set; the 15 fresh queries compensate
  partially but are docstring-derived.
