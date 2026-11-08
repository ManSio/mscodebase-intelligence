# Ideal-system patterns — research synthesis (2026-09-25)

Sources: dev.to posts + comment threads (live API), plus web (Temporal, ES/Solr,
Postgres, LangChain). Each pattern is a rule we can implement, anchored to its source.

## Patterns

### P-A. "Green while broken" — status != health
Source: "Uptime Is Not an Agent SLO" — raju_dandigam (4619821) + comments.
Rule: an endpoint can be 200 / an indicator 95% while the outcome is wrong. Use a
**scorecard of separate indicators** (availability / outcome / safety / latency /
efficiency / escalation), never one blended number; "do not average safety into
availability". Track **unknown-outcome rate** separately.
Our case: job showed "Finalizing 95%" while hung = availability green, product dead.

### P-B. "still digging" == "hung" without a heartbeat
Source: Temporal long-running-activity heartbeat pattern; Raven issue #153.
Rule: long tasks must emit **per-phase heartbeat + progress details + wait_reason**
(what are we waiting on — lock/IO/native), with **stall detection** (no heartbeat
N sec in an active phase => STALLED, not "in progress").

### P-C. Failure result is multi-axis, not PASS/FAIL
Source: "I Injected the Same Failures Into 5 MCP SDKs" — anilloutombam (4694934) +
comments (raju_dandigam, mihai_leanzero).
Rule: report (1) conformance, (2) **session survivability** (send a normal request
AFTER the fault), (3) **diagnostic visibility**. "Triggering a fault only tells you
what happened during the fault; it doesn't tell you whether the state survived it."

### P-D. Diagnostic visibility is a first-class axis
Source: same + MCP error envelopes (Orisu/Perplexity/xAI, GitHub style guide).
Rule: every failure carries `{code, message, next_action, details}` so an agent can
branch and recover. Format: "what's wrong -> what's expected -> example".

### P-E. Deterministic failure injection is the guard's guard
Source: MCP Failure Lab (4694934); our own guard-inventory doctrine.
Rule: a guard that cannot fail is worthless. Inject the failure deterministically
and assert recovery + visibility.

### P-F. Metric bug families (numbers go wrong)
Source: "We audited 110 AI usage tools" — roytong (4719629) + comments.
- F1 **stale constants** quoted confidently (=> our `graph_score=0.4`, frozen ETA).
- F3 **retry double-counting** (byte-identical re-emits counted twice => our dup/bloat).
- F4 **absent treated as zero** (`or 0` turns "unknown" into "free"; rollups must be
  able to say **UNPROVABLE**, not 0) => our exp-16 "0 eligible vs 0 collected".
- F5 **window-boundary / absolute-date fixtures** (passes 30d, fails everywhere) =>
  our absolute-date test flakes.
Rule: numbers must be traceable to named rules; allow UNPROVABLE; verify your own bill.

### P-G. Incremental correctness
Source: shirokoff "RAG freshness"; LangChain Indexing API; Solr signature dedup;
canopyide FTS5 issue; Hermes storage diet.
Rule: update = **delete-then-insert by content hash** (not upsert); stable doc id
(path is not an id); doc->chunk lineage for delete-by-filter; FTS5
**delete-before-add** (stale tokens otherwise); **delete test on day one**;
query-time freshness check. Supplementary: 3-layer dedup (exact hash -> Jaccard ->
cosine).

## Gap -> pattern map
- 3 disagreeing indicators + stale ETA => P-A, P-B, P-F1.
- hung job invisible => P-B, P-C.
- `{"ok":false,"error":"..."}` no hint => P-D.
- index ~2x bloat, FTS5 add-only => P-G, P-F3.
- guard blind spots (optimize untested) => P-C, P-E.

## Roadmap (each slice: Phase Zero -> Experiment -> Fix -> Guard -> Record)

> **Status audited 2026-11-08** against `main` with commands, not from memory:
> `grep -r error_envelope src/` (2 hits after wiring: `error_handler.py:29-30`),
> `grep -r wait_reason src/` (0), `grep -r integrity_report src/` (0),
> `grep -c run_bounded src/**` (14 call sites), `grep watchdog_heartbeat`
> (parse/write/embed/text-index only), stall watchdog at
> `src/core/intelligence/layer.py:2025`.

- S1 **[done 2026-11-08]** error_envelope core (P-D). `src/core/error_envelope.py` is
  now imported by `src/core/error_handler.py`; `ToolError` carries a `code`
  (`IndexNotReadyError` → `INDEX_NOT_READY`, `RateLimitError` → `RATE_LIMIT`,
  timeout → `TIMEOUT`).
- S2 **[done 2026-11-08, breaking]** wire envelope into MCP error paths (P-D).
  All 55 `@error_boundary` decorations (20 files, `git grep -c "@error_boundary" src/`)
  return the JSON envelope instead of a Markdown
  block; dictionary results with an error-like `status` go through the same path
  (this also fixed a "green while broken" bug — those dicts were rendered as
  "✅ Completed"). Owner decision: breaking format change.
  Guard: `tests/test_error_envelope_wiring.py` (17 tests, with negative controls).
  Residual: MCP-level `isError` is still `false` — the envelope is normal output.
- S3 [partial] per-phase heartbeat + stall detection + wait_reason (P-A/P-B):
  stall detection **done** (`_REINDEX_STALL_SEC` + finalize), heartbeat covers
  parse/embed/write/text-index only, `wait_reason` **absent**.
- S4 [open] learned per-phase ETA, UNPROVABLE allowed (P-B/P-F1/P-F4). Only a single
  `reindex_eta_sec` scalar exists (layer.py:591), no per-phase learning.
- S5 [partial] incremental correctness: hash-gate delete-then-insert **done**
  (`_index_single_file` + `_index_text_only_project`), FTS5 delete-before-add **done**
  (`remove_from_fts5` before `incremental_update_fts5`); dedup, delete test and
  integrity report still missing.
- S6 [open] failure-injection lab for the indexer/watchdog; multi-axis results (P-C/P-E).
  No `tests/*inject*` exists.
