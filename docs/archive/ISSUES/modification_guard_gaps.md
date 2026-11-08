# Issue: modification_guard — connected but 3 architectural gaps remain

## Status: Partially addressed (2026-07-23)

**What was found:** `src/core/modification_guard.py` implements a full decorator
`modification_guard(pagerank_min, blast_min, ack_ttl)` with deny logic based on
PageRank/blast radius. Grep across all `src/` found zero `@modification_guard`
or calls to the factory — only `ack_impact` (the acknowledgment endpoint) was
used. The guard was inert.

**What was done:** Connected `@modification_guard` to `WriteTool.execute()` and
fixed fail-open → fail-closed in lookup functions.

**What remains (3 gaps, need decision):**

## Gap 1: Self-ack without impact_analysis verification

`ack_impact(file_path)` is a plain function — nothing verifies that `impact_analysis`
was actually called before it. An agent or script can call `ack_impact("hot_file.py")`
before every write, completely defeating the guard. Need at minimum token/hashing
linkage with the result of `impact_analysis`.

**Action:** Decide whether to require a result token from `impact_analysis()` or
accept the current advisory-level protection.

## Gap 2: Guard reads only kwargs

`file_path = kwargs.get("file_path", "")` — if a wrapped tool is ever called with
positional args instead of kwargs, `target_path` stays empty and the early-return
at line 116 (`if not file_path and not symbol: return await func(...)`) silently
bypasses the guard with zero logging. Fragile coupling between protection and
MCP tool dispatch.

**Action:** Make the guard extract target from positional args too, or enforce
kwargs-only dispatch in `WriteTool.execute()`.

## Gap 3: fail-closed on DI error may cause false denials

With fail-closed (current), if `ProjectIndexerRegistry` is not yet initialized
(project not indexed), EVERY write operation is denied until `ack_impact` is called.
This is correct from security posture but may cause friction in normal workflow.

**Action:** Decide if there should be a "first-run bypass" for projects that haven't
been indexed yet, or if requiring ack on every write in unindexed projects is acceptable.
