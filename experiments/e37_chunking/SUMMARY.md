# E37 — line-granularity chunking simulation (48 real queries)

**Panel:** E30 48 queries, corrected index (symbol_name populated), E33 demote ON,
P3 off, no embeddings, no reranker. Chunking is simulated by splitting existing
chunk text into line windows (25% overlap) and building temporary SQLite/FTS5
stores.

| Arm | hit@1 | hit@5 | MRR | p50 |
|---|---:|---:|---:|---:|
| current (function-level) | 0.688 | 0.771 | 0.713 | 151 ms |
| split32 | 0.688 | 0.771 | 0.713 | 161 ms |
| split64 | 0.688 | 0.771 | 0.713 | 131 ms |
| split128 | 0.688 | 0.771 | 0.713 | 136 ms |

**Result:** identical quality for every chunk size. Chunk granularity is not the
bottleneck on this panel; the file-level ranking/candidate set is. Splitting
increased the split32 store to 18,818 rows (from 16,347) but did not change top-5.

**Caveat:** this is a simulation over already-parsed chunk text, not an AST-aware
re-chunking of the full files. The original chunks are already mostly ≤32 lines
(13,992 / 16,347), so the tested range is narrow.

**Next:** code-aware reranker (Qwen3-Reranker-0.6B) or query expansion/semantic
anchors — deterministic chunking/tokenization/graph/PRF are exhausted on this panel.
