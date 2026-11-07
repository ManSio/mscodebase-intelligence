# E36 — deterministic pipeline ablation + symbol_name audit

## Critical data bug (found by this audit)

`write_text_records` read `symbol_name` from `chunk_metadatas`, where the parser
never put it → **0 / 16,158 chunks had a symbol_name**. FTS5/BM25 name boosts,
exact-name metadata and graph hydration were dead. E32–E35 were measured on that
corrupted index.

**Fix:** `IndexPipeline.process_file` maps AST symbols to chunk line ranges.
After text-only reindex: **4,772 / 16,347** chunks with symbol_name, graph
13,980 nodes / 46,546 edges.

Also fixed:
- `_graph_stage` returned synthetic pointers and absolute paths → now hydrates
  the real chunk (`get_symbol_chunk` / `get_chunk_near_line`) and normalizes paths.
- P3 module-head anchor was dead (`_bm25_df=None` in SQLite mode) → now reads
  `SQLiteChunkStore.get_file_head`; P3 is off by default because it costs ~96 ms
  without a reranker and does not change top-5.

## Ablation (48 real queries, corrected index)

| Arm | hit@1 | hit@5 | MRR | p50 |
|---|---:|---:|---:|---:|
| **full** | **0.688** | **0.771** | **0.713** | 183 ms |
| no_expansion | 0.688 | 0.771 | 0.713 | 185 ms |
| **no_bucket** | **0.562** | 0.750 | 0.647 | 186 ms |
| no_cochange | 0.688 | 0.771 | 0.713 | 184 ms |
| no_p2 | 0.688 | 0.771 | 0.713 | 171 ms |
| **no_p3** | 0.688 | 0.771 | 0.713 | **87 ms** |
| no_o1 | 0.667 | 0.771 | 0.703 | 173 ms |
| no_exact | 0.688 | 0.771 | 0.713 | 183 ms |
| no_dedupe | 0.688 | 0.750 | 0.713 | 185 ms |
| no_graph | 0.688 | 0.771 | 0.713 | 188 ms |
| no_demote | 0.625 | 0.750 | 0.671 | 194 ms |
| minimal | 0.542 | 0.750 | 0.636 | 64 ms |

## What actually matters

- **Bucket weights** (docs ×0.5): +5 hit@1 — critical.
- **Demote non-code** (E33): +3 hit@1 — critical.
- **O1 rare-identifier boost:** +1 hit@1.
- **Dedupe by symbol:** +1 hit@5.
- **P3:** 0 quality, +96 ms without a reranker → off by default.
- Query expansion, co-change, P2, exact-name, graph stage: no effect on this panel.
- The corrected full pipeline is **0.688 hit@1 / 0.771 hit@5**; P3-off keeps the
  same quality at **87 ms**.

## Status

- Source fixed; index rebuilt with symbol_name.
- `MSCODEBASE_P3_ANCHOR=false` added (off by default).
- E37 (chunking) ran after this fix: 32/64/128-line chunks all equal 0.688/0.771
  → chunk granularity is not the bottleneck on this panel.
