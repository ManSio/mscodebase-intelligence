# P3 module-head anchor — live result (2026-09-29): FALSIFIED

Mechanism implemented per `PREREG.md` (`_anchor_module_head_chunks_async`,
`engine.py`, P2-style, caps `_O1_ANCHOR_TOTAL` / `MAX_RERANKER_INPUT=30`,
`MIN_RERANK_SCORE=0.3` untouched). Live holdout validation
(`scripts/p3_holdout_gate.py`, fresh process, FTS prebuild + discarded warm-up
+ per-case reranker-cache clear, BGE-M3 on :8081, embed on :8080) REJECTS the
prereg expectation: **P3 rank None (expected 1), R2 rank None (expected 1)**.

## What was verified live (mechanism works as coded)

Pre-rerank pool capture for the P3 query
(`ArtifactGC _cleanup_old_projects 30d 90d 7d retention_policy`): pool n=8,
`src/core/artifact_gc.py:0` present with `module_head_anchor=True`, pool cap
respected. The anchor does what the spec says.

## Why the hit does not happen (two load-bearing findings)

1. **chunk_index 0 is not a docstring chunk — for ANY file.** The AST chunker
   drops module-level docstrings index-wide (verified: `artifact_gc.py` has 6
   chunks, all function-scoped; chunk 0 = `def _dir_has_files`, len 279;
   `engine.py` chunk 0 = `def _cache_key`; `graph.py`, `llama_runner.py`
   likewise first-function). The probe passage that scores +0.83 (`gold_doc`,
   first 800 chars of the file) does not exist as an indexed chunk. The real
   chunk 0 scores **-6.66** on the P3 query — correctly cut. No pool-anchor can
   place a chunk the index never built. Prereg clause (i)/(ii) fire.
2. **The EXPERIMENTS_LOG:2813 sigmoid fix is absent from the code.**
   `grep sigmoid src/` = zero hits; the llama_cpp path stores raw logits in
   `reranker_score` (`multi_provider.py:500-502`, `apply_scores`) and filters
   them against `MIN_RERANK_SCORE=0.3` (`multi_provider.py:670`). Live winner
   for P3 was a junk JSON chunk at logit +1.65; FINAL n=1. Out of scope here
   (threshold untouched by design), but it explains the all-None holdout rows.

## Full holdout table (branch, rev e5756f55 + anchor)

```
P2  rank=1    n=2  (no P2 regression)
P3  rank=None n=1  | R2 rank=None n=1
H1  None n=1 | H2 None n=1 | H3 None n=1 | H4 2 n=2 | H5 1 n=5 | H6 2 n=3
H7  None n=1 | H8 1 n=5 | H9 None n=5 | H10 None n=1 | H11 2 n=2 | H12 None n=1
N1  None (negative control, clean) | DOC None (doc-control, clean)
```

Controls clean throughout: no unexpected boosts, no doc boosts, no
reranker-cache voids, no degraded rows (reranker ran every query,
`model=llama.cpp-reranker`). H-rank Nones are threshold cuts (finding 2),
not anchor demotions — the anchor is append-only pre-rerank and cannot demote
a chunk that passes the threshold.

## Verdict

FALSIFIED per prereg rule. No PR opened (nothing to propose). Next step, if
wanted, is index-level, not pool-level: emit a module-docstring chunk at index
time (parser/indexer change + reindex), then re-run this gate. The mocked
suite (`tests/test_p3_module_head_anchor.py`, 9 passed) and the gate script
stay on the branch as the reusable harness for that attempt.
