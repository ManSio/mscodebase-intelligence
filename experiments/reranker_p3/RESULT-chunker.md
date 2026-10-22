# Chunker module-docstring fix — live gate result (2026-09-29): RED (mechanism delivered, retrieval blocks)

Branch: `fix/chunker-module-doc` (off `origin/main` + cherry-picked P3 stack:
anchor `d3d53075`, sigmoid `f2df8160`). Task: emit module docstring as chunk 0.

## 1. Mechanism (implemented, unit-verified)

`src/core/indexing/parser.py`: `_extract_module_docstring` (stdlib `ast`,
.py only) + `chunks.insert(0, …)` in `_parse_with_tree_sitter` (only when the
walk already produced chunks — fallback path untouched), `hierarchy_map`
`module_docstring → module`, symbol `__module_doc__`. Files without a
docstring: byte-identical behavior. Symbols untouched (no graph pollution).

`tests/test_chunker_module_doc.py`: 5 passed. Related suites green:
`test_parser.py` 5, `test_p3_module_head_anchor.py` 9,
`test_chunk_cache.py` + `test_move_chunks.py` + `test_scm_definitions.py` 45.
`ruff check` clean on both files (`ruff format` not enforced repo-wide —
all pre-existing files fail it too; new code matches file style).

## 2. Live reindex (evidence)

- BEFORE: 15,426 rows, 0 `module_docstring` rows; `artifact_gc.py` 6 chunks,
  chunk 0 = `function_definition` (`def _dir_has_files`).
- Method: wipe `delete("1 = 1")` (no rmtree — live servers hold the DB open)
  + `indexer.index_project(project)` with working-tree code, embedder :8080.
- AFTER (repaired, see §4): **14,839 rows**, **371 `module_docstring` chunks**,
  0 dup `(file_path, chunk_index)`; `artifact_gc.py` 7 chunks,
  chunk 0 = `module_docstring` (start_line 1, head = file docstring).
- Direct rerank of the new chunk 0 on the P3 query: **logit +1.21 / sig 0.77**
  (probe predicted +0.83; old chunk 0 scored −6.66 and the probe passage did
  not exist). Chunk 1 scores −6.52 → correctly cut. The chunker half of the
  drill-down is closed.

## 3. Gate (fresh process, `scripts/p3_holdout_gate.py`, rev `f2df8160`)

```
P2  rank=2    n=5  (expected 1 — REGRESSION vs FALSIFIED baseline rank 1)
P3  rank=None n=2  (expected 1) | R2 rank=3 n=3 (expected 1; was None)
H1  3 n=3 | H2 None n=1 | H3 3 n=3 | H4 2 n=2 | H5 1 n=5 | H6 3 n=5
H7  None n=1 | H8 1 n=5 | H9 None n=5 | H10 None n=1 | H11 1 n=4 | H12 2 n=3
N1  None (clean) | DOC None (clean)
```

Controls clean throughout: no unexpected boosts, no doc boosts, no
reranker-cache voids, no degraded rows, no timeouts
(`model=llama.cpp-reranker` every row — sigmoid fix confirmed live).

## 4. Analysis (why RED)

1. **Retrieval never surfaces any `artifact_gc.py` chunk for the P3 query.**
   FINAL n=2 are both JSON experiment artifacts
   (`reranker_p3/rerank_probe_run1.json:0`, `noderag/results/results.json:1`).
   The P3 query's distinctive terms (`_cleanup_old_projects`,
   `retention_policy`) occur verbatim in OUR OWN probe/result JSON
   (verified by grep) and nowhere in `artifact_gc.py` — they dominate BM25
   while the 0.77 doc chunk sits outside the pool. The P3 pool-anchor can
   only anchor chunk 0 of files *already in the pool*; with zero pool chunks
   from the target file it cannot fire. Design-level finding, not an
   implementation bug. Fixing it means broadening retrieval/anchor scope —
   beyond this task's minimal chunker brief.
2. **P2 rank 2 is run-to-run noise, not a chunker regression.** A follow-up
   fresh-process P2 run put `engine.py:35` back at rank 1; that run logged
   `FTS5 search timed out (>2s), skipping FTS5 tier` — tier membership
   flip-flops (~2.18s prebuild vs 2s budget) and moves ranks 1↔2. Same noise
   class explains H6 2→3 / H11 2→1 / H12 None→2 wobbles. H-set: no systematic
   demotion (H5=1, H8=1, H11=1 hold; R2 None→3 and H12 None→2 improved).
3. **Infra incidents during this run (caveats):**
   - Double-write: post-reindex table held 29,134 rows (every chunk twice,
     identical ids). In-run mechanism unproven; repaired deterministically
     (pandas dedup by id → wipe → single re-add, round-trip validated on a
     scratch table first: vectors/text identical). AFTER = 14,839 verified.
   - `_safe_ivf_index` (optimize/create_index) aborted: PID lock held by live
     MCP servers (pid 2944/13172). Table now has NO vector index (flat exact
     scan — correct, slightly slower; fine for the gate). Owner should run
     `intel_trigger_reindex(full)` or Reload-Window Zed so the servers
     re-open the table (their handles predate the wipe) and finalize IVF.
   - Unrelated dirt `experiments/planted_break/results.json` was already
     modified before this task — left untouched, unstaged.

## Verdict

RED per gate rule (P3 None, P2 2, R2 3 — all expected 1). No PR opened.
Chunker fix stands on its own (unit + live verified); P3 rank 1 needs a
retrieval-side follow-up (anchor scope / BM25 competition from experiment
JSON artifacts), proposed as the next drill-down level, not this branch.
