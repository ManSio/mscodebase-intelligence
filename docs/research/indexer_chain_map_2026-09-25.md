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
| 3 | `_verify_and_repair_table_integrity` | **yes (native)** | no heartbeat | **bounded** (`_bounded_link "verify_integrity"`) |
| 4 | known_hashes `to_lance().to_pandas` | **yes (native)** | no | **bounded** (`"known_hashes_load"`, default `None`) |
| 5 | Phase 1 parse (ThreadPoolExecutor) | was yes | heartbeat `parse:{name}` + progress "parsing" | **bounded** (run_bounded 60s/file) |
| 6 | embed `embedder.embed_batch` | **yes (llama.cpp)** | heartbeat `embed:done/total` + progress "embedding" | **bounded** (`"embed_batch"`, fatal=True) |
| 7 | per-file `bulk_write` (LanceDB) | **yes (native)** | heartbeat `write:{name}` | **bounded** (`"bulk_write"`, fatal=True) |
| 8 | `_safe_prune` | **yes** | no | **bounded** (`"prune"`) |
| 9 | BM25 reindex (`searcher`) | **yes** | no | **bounded** (`"bm25_reindex"`) |
| 10 | `_safe_ivf_index` (optimize/create_index) | was yes | progress "finalizing" 0.95 | **bounded** (run_bounded) |
| 11 | `summarizer.save_cache` | yes | no | **bounded** (`"summarizer_save"`) |
| 12 | `save_symbol_index` | **yes (native)** | no | **bounded** (`"save_symbol_index"`) |
| 13 | post-run: symbol index / auto-doc (`layer`) | yes | job.progress 0.8->1.0 | auto-doc: to_thread + wait_for(300) |
| S | search: `hybrid_search_async` (dense/FTS5/BM25/rerank/graph) | yes | intel_tool_health/latency | embedded bounds (some run_bounded now) |

## Findings from the chain — status re-checked 2026-11-08 (CORRECTED)

> **Correction.** An earlier revision of this section claimed that prune, BM25,
> `save_symbol_index` and `summarizer.save_cache` were still unbounded. That was wrong:
> every link except `os.walk` goes through `_bounded_link` → `run_bounded`
> (`MSCODEBASE_LINK_TIMEOUT_SEC`, default 300 s). The claim was never re-verified before
> being written down; the table above is now the source of truth.

> Verified with: `git grep -n "_bounded_link\|run_bounded(" src/core/indexing/index_project_runner.py`
> → `verify_integrity:362`, `known_hashes_load:375`, `bulk_write:512`, `prune:464/678`,
> `bm25_reindex:468/687`, `embed_batch:555`, `summarizer_save:712`, `save_symbol_index:715`,
> `ivf-*:773`.

- **Unbounded native calls — CLOSED.** Every non-cancellable link of the chain is bounded.
  A native stall now aborts that link in ≤300 s (fatal links raise a resume-safe error,
  non-fatal ones are skipped and the index stays usable) instead of freezing the phase.
- **Observability of those links — still partial.** `watchdog_heartbeat` is emitted only at
  `parse:{name}` (:448), `write:{name}` (:526, :614), `embed:{done}/{total}` (:650) and
  `text-index:{n}/{total}` (indexer.py:1006). verify/prune/BM25/save are silent for up to
  300 s — bounded, but blind.
- **`wait_reason` — DONE (2026-11-08).** `src/core/indexing/wait_state.py` records
  the current bounded link; every `_bounded_link`, the parse call and the IVF bound
  set/clear it, and `wait_reason` is exposed by `indexer.get_status()`,
  `codebase(action="index", path="status")` and the reindex telemetry
  (`reindex_in_progress` block). Labels look like `native:prune`,
  `native:embed_batch`, `native:ivf-create_index`, `native:parse:<file>`.
  Deliberately not reported: the write lock — `run()` holds it for the whole
  reindex, so "waiting on lock" would be true almost always; cross-process
  contention already surfaces as the read-only mode message. Guard:
  `tests/test_wait_reason.py` (9).
- **Stall detection — DONE (2026-10/11).** `_REINDEX_STALL_SEC` (default 900 s) plus
  `_finalize_stalled_*` in `src/core/intelligence/layer.py:2025+` marks a silent
  reindex as failed and writes a ledger row, instead of leaving "95 % Finalizing".

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
