# Indexer chain map — end to end (2026-09-25)

Full pipeline inventory: every link, whether it can hang, what is observable, what
guard exists. Purpose: build the nervous system (S3) from facts, and bound every
non-cancellable native call (same class as the fixed `_safe_optimize`).

Source: `index_project_runner.run()` (255-630), `layer._run_reindex_job` (730-800),
`db_writer`, `engine.hybrid_search_async`.

## Chain (trigger -> done)

| # | Link | Can hang? | Observable now | Guard now |
|---|------|-----------|----------------|-----------|
| 0 | path safety check | no | — | is_safe_to_process |
| 1 | `begin_write()` lock | yes (waits) | — | soft-wait on live holder |
| 2 | `os.walk` scan | slow only | progress "scanning" 0/total | none |
| 3 | `_verify_and_repair_table_integrity` | **yes (native)** | no heartbeat | none |
| 4 | known_hashes `to_lance().to_pandas` | **yes (native)** | no | none |
| 5 | Phase 1 parse (ThreadPoolExecutor) | was yes | heartbeat `parse:{name}` + progress "parsing" | **bounded** (run_bounded 60s/file) |
| 6 | embed `embedder.embed_batch` | **yes (llama.cpp)** | heartbeat `embed:done/total` + progress "embedding" | **none** (no per-batch bound) |
| 7 | per-file `bulk_write` (LanceDB) | **yes (native)** | heartbeat `write:{name}` | **none** |
| 8 | `_safe_prune` | **yes** | no | none |
| 9 | BM25 reindex (`searcher`) | **yes** | no | none |
| 10 | `_safe_ivf_index` (optimize/create_index) | was yes | progress "finalizing" 0.95 | **bounded** (run_bounded) |
| 11 | `summarizer.save_cache` | yes | no | none |
| 12 | `save_symbol_index` | **yes (native)** | no | none |
| 13 | post-run: symbol index / auto-doc (`layer`) | yes | job.progress 0.8->1.0 | auto-doc: to_thread + wait_for(300) |
| S | search: `hybrid_search_async` (dense/FTS5/BM25/rerank/graph) | yes | intel_tool_health/latency | embedded bounds (some run_bounded now) |

## Findings from the chain (not yet fixed)
- **Unbounded native calls remain (#3,#4,#6,#7,#8,#9,#11,#12)** — the same
  non-cancellable class as `_safe_optimize`; any native stall freezes the phase.
- **Heartbeat coverage is partial**: only parse/embed/write emit `watchdog_heartbeat`
  and progress. prune/BM25/IVF/symbol/docs are dark.
- **No `wait_reason`**: when CPU is 0 and the phase "runs", nothing says what it waits
  on (lock / IO / native). Postgres `wait_event` has this; we don't.
- **No stall detection**: nothing turns "no heartbeat for N sec in an active phase"
  into STALLED. The job stays "95% Finalizing" forever (P-A/P-B).

## Experimental protocol (per slice, per §5/§7)
Each slice ships: (a) Phase-Zero note, (b) deterministic **failure injection** of the
link under test, (c) fixed version, (d) **negative control that must fail on old code
and pass on new**, (e) full-chain smoke (index a real repo end-to-end), (f) record.
Acceptance is multi-axis (P-C): conformance + session/state survivability + diagnostic
visibility — never a single PASS.

## Roadmap link coverage
- S3 (nervous system): add `wait_reason` + heartbeat to ALL links + stall detector.
- S4 (ETA): per-phase learned durations; UNPROVABLE when no driver (P-F).
- S5 (incremental): #7/#8/#9 correctness (delete-then-insert hash-gate; FTS5
  delete-before-add; dedup) + integrity report.
- S6 (failure lab): inject hang at #3/#4/#6/#7 and assert bounded + visible.
- Fix pass: bound #3,#4,#6,#7,#8,#9,#11,#12 with `run_bounded`.
