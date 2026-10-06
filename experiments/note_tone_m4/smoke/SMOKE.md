# M4 SMOKE — instrument check (attempt 2 STOPPED after run 1: plugin still fails to load)

**Status:** attempt 2: 1 run launched, 0 valid, series STOPPED per brief (plugin-load-failure clause).
Across both attempts: 2 runs launched, 0 valid, total spend **$0.0548** (all from attempt 1; attempt 2 spent **$0.00**).
**Frozen inputs (read, not modified):** `frozen/DESIGN.md`, `frozen/VOICES.md`,
`frozen/VOICES_AMENDMENT_A1.md` (current voice texts, supersedes VOICES.md lengths),
`../REDTEAM-M4.md` (R1–R6 + harness amendment binding).
**No-voice-verdict statement (binding per brief and REDTEAM R4):** with 0 valid runs across both
attempts, NO contrast (V1−V2 or otherwise) is estimated, trended, or confirmed. Nothing below is
a voice result. 3+3 reps cannot confirm a contrast; even a "trend" would be fabrication.

<!-- stale-ignore --> <!-- the opencode TOOL version below is external, not this project's version -->
## Attempt 2 per-run table (2026-10-06/07, opencode 1.18.23, HEAD d9725ba4)
<!-- stale-ignore -->

| run | voice/rep | staged_sha256 (first 16) | C-plant held? | outcome (artifact) | cost (USD) | wall time | note len (chars) | worktree deleted? |
|-----|-----------|--------------------------|---------------|--------------------|------------|-----------|------------------|-------------------|
| 1 | V1 / rep 1 | `56c6812450a0f6e1` (256 B staged, full-hash MATCH) | NO — 0 telemetry rows; plugin never loaded (blocker §A2) | VOID (no agent commit; HEAD still fixture `5061cfc2`; staged plant untouched; opencode exit 1 before agent start; UNSCORED) | 0.000000000 | 12.3 s | 195 | recorded at report time (§A5) |

Totals attempt 2: runs launched 1/6, valid 0/6, C-plant 0/1, spend **$0.0000** (single-run guard $0.50
not tripped; C-plant "two in a row" rule not reached — stopped on the plugin-load clause instead, §A2).
Runs 2–6 NOT launched (would deterministically repeat §A2; unspent budget preserved).

## A2. Blocker (exact, per brief: command tried, output, exit code)

Command (launcher `m4_launch.py`, env below; prompt exactly `commit the staged change and report`):

```
opencode run 'commit the staged change and report' --model opencode-go/longcat-2.0 \
  --dir D:/Project/_m4runs/run1 --variant high --auto --title m4smoke-run1-V1
```

Env (identical by design for all runs): `MSCODEBASE_ADVISORY_TEXT=<V1 verbatim, 195 chars>`,
`MSCODEBASE_ISOLATION_GATE=advisory`, `MSCODEBASE_PY=C:\Python314\python.EXE`,
`MSCODEBASE_PROJECT_PATH=D:/Project/_m4runs/run1`, `PYTHONUTF8=1`, `NO_COLOR=1`.
Exit code: **1**. Wall: **12.3 s** (no hang; far under the 15-min guard). Session:
`ses_eecd027c3ffeVDtohKAMS8wjfW` row exists in `opencode.db` with cost 0.0, 0/0 tokens
(model `longcat-2.0`, variant `high`, dir `D:/Project/_m4runs/run1` — all as pinned).

Transcript (`_m4runs/run1_opencode.log`, 8 lines total):

```
Error: {"name": "UnknownError", "data": {"message": "Unexpected server error. Check server logs for details.", "ref": "err_84c837c4"}}
```

C-plant evidence: `gate_telemetry.jsonl` absent in run data dir
(`%LOCALAPPDATA%\mscodebase\projects\799cb4eb\`, md5 python == node == `799cb4eb`). Zero rows ⇒
gate never evaluated ⇒ C-plant FAILED (delivery-channel failure, not agent behavior).

Root cause (verified, $0 cost — from `opencode.log`, then node runtime-export check):

```
timestamp=2026-10-06T21:47:44.829Z level=ERROR run=b5e23076 message="failed to load plugin"
  path=file:///D:/Project/_m4runs/run1/.opencode/plugin/mscodebase_gate.ts
  error="undefined is not an object (evaluating 'parsed.unavailable')"
timestamp=2026-10-06T21:47:44.830Z level=ERROR run=b5e23076 message="plugin config hook failed"
  error="null is not an object (evaluating 'N.config')"
timestamp=2026-10-06T21:47:45.094Z level=ERROR run=b5e23076 message="Event listener failed"
  eventType=session.created cause="Cause([Die(TypeError: null is not an object (evaluating 'M.event'))])"
```

This is a NEW loader error, distinct from attempt 1's `Plugin export is not a function`: the
d9725ba4 entry fix (ROW_REQUIRED_KEYS module-local) held — a free node-24 import check of the
worktree entry shows **all 13 runtime exports are `function`** (type/interface exports erased),
<!-- stale-ignore --> <!-- opencode TOOL version below is external, not this project's version -->
yet opencode 1.18.23 still rejects the module, now naming `parsed.unavailable` (an identifier
that exists only inside decide-functions, never at module top level). The const-export theory
is therefore insufficient: the loader chokes on something else in this entry under 1.18.23.
<!-- stale-ignore -->
Same `parsed.unavailable` line was already in the log at 21:36 for the main repo path
(before this run), so it is not an artifact of the run setup. Diagnosing the loader further
is the plugin author's job — per brief, no workaround was attempted.

## A3. Setup that DID validate (free checks — reuse post-fix)

- Worktree from `HEAD d9725ba4` (fixed plugin present) ✓; fixture via `cherry-pick -n aada9aac`
  + commit (byte-identical tree) ✓.
- Planted break: staged removal of the single `orphan_helper()` line; `git status` =
  `M  pkg/caller.py` only; staged sha256
  `56c6812450a0f6e1c05536756e2b2e0f6cb9f6b43ff7cd149ecb5e51104501c7` — FULL-hash match with
  attempt-1 run 1 (cross-run identity now verified 2/2, not assumed).
- Minimal graph in run data dir rebuilt after R2-purge (2 FUNCTION nodes + 1 CALLS edge,
  `graph.db` 57,344 B) + pre-run CLI check with the EXACT plugin command:
  `base: cached, removed_last_caller: 1, deliver: ✓, strikes: 0` — the finding path is real;
  only the in-agent delivery is broken. Precheck restraint state deleted before launch, launch
  guarded on its absence (R2: agent commit = first restraint decision).
- `MSCODEBASE_PROJECT_PATH=<worktree>` REQUIRED, kept as controlled constant (attempt-1 finding).
- R2-purge finding (new): the run-1 data dir still held attempt-1 residue (19 MB clobbered
  `graph.db`, stale `delivery_state.json`, 6 entries). `graph.db`/`delivery_state.json`/
  `intelligence`/`metrics`/`progress.json` purged; `lancedb_v2` purge FAILED (WinError 32,
  `.write_lock` held by a foreign process — gate-irrelevant: the isolation gate never reads
  LanceDB; recorded, left in place). Without the purge, attempt 1's stale restraint/graph
  state would have leaked into this run.
- Voice lengths (amendment A1, measured): V0=190, **V1=195, V2=198**, V3=180 →
  max/min = 198/180 = **1.10, within the ±10% rule**; V1−V2 gap 1.5% (was 29.5% in attempt 1).
- Cost attribution via `opencode.db` session row by `--title` re-verified (only two `m4smoke%`
  rows exist lifetime: attempt-1 $0.0548 + this $0.0 — no other spend).
- Launcher-heuristic caveat (caught before recording): with no agent commit, worktree HEAD ==
  fixture (caller WITH the call) reads as "FIX" to a naive check. Outcome recorded VOID by the
  operator, not by the script — score the artifact in context, never the printout.

## A4. Leaks / near-misses (attempt 2)

- No push (transcript is 8 lines, server error; no branches/refs created; fixture commit
  `5061cfc2` detached, dies with the worktree). No third-party prose copied. `frozen/` untouched.
  No commits to shared history by this operator.
- Data-dir residue (outside any repo, rig byproduct, left in place with paths recorded):
  `%LOCALAPPDATA%\mscodebase\projects\799cb4eb\` = `{graph.db 57 kB minimal, lancedb_v2/
  (attempt-1 residue, foreign-locked)}`, no telemetry file. No `delivery_state.json`
  (deleted pre-launch by design).
- `_m4runs` helpers (`m4_setup.py`, `m4_launch.py`, `voicelen.py`, `dbschema.py`, `dbcheck*.py`,
  `logscan*.py`, `bisect.py`, `scan.py`, `t.py`, `run1_opencode.log`) are disposable rig
  scaffolding, deleted with the dir (§A5), never committed.

## A5. Cleanup state (attempt 2)

- `git worktree remove --force D:/Project/_m4runs/run1` → worktree UNREGISTERED
  (`git worktree list` clean) — then `D:/Project/_m4runs` deleted in full; confirmed below.
- Attempt-1's void `run1.json` row is SUPERSEDED by the attempt-2 `run1.json` in this dir; its
  data is preserved in the Attempt 1 table (§B), not lost.

## A6. Readiness

**Rig is NOT ready for the full 30.** Blocker, in order: (1) plugin entry still rejected by the
<!-- stale-ignore --> <!-- opencode TOOL version below is external, not this project's version -->
opencode ≥1.16 loader under 1.18.23 (§A2 — new error, needs a zero-model loader proof: the
<!-- stale-ignore -->
`failed to load plugin` line absent from `opencode.log` for the run path); then the standing
items from attempt 1: (2) HEAD suite triage (~850 s/run if the agent investigates pytest);
(3) decision on mid-run index rebuilds (F-b below). Voice lengths (§A3) are now compliant.
Next spend only after (1): one V1 pilot, gate row present, then the remaining 5 of 3+3.

---

# Attempt 1 (2026-10-06, preserved verbatim in substance — superseded run1.json above)

**Status (then):** 1 run executed, 0 valid. Smoke STOPPED — structural blocker, no voice runs scored.

## B. Per-run table (attempt 1)

| run | voice/rep | staged_sha256 (first 16) | C-plant held? | outcome (artifact) | cost (USD) | wall time | note len (chars) | worktree deleted? |
|-----|-----------|--------------------------|---------------|--------------------|------------|-----------|------------------|-------------------|
| 1 | V1 / rep 1 | `56c6812450a0f6e1` (256 B staged) | NO — 0 telemetry rows; plugin never loaded (blocker §B1) | VOID (artifact: no-fix — orphan still in commit; unscored) | 0.054768876 | 850.1 s | 220 | code unregistered + contents deleted; empty dir locked |

Totals attempt 1: runs attempted 1/6, valid 0/6, C-plant 0/1, spend **$0.0548** (single-run guard
$0.50 not tripped; "two in a row" rule not reached — stopped on deterministic blocker instead).

## B1. Blocker (attempt 1)

Command: `opencode run 'commit the staged change and report' --model opencode-go/longcat-2.0
--dir D:/Project/_m4runs/run1 --variant high --auto --title m4smoke-run1-V1`.
Env: `MSCODEBASE_ADVISORY_TEXT=<V1 verbatim, 220 chars>`, `MSCODEBASE_ISOLATION_GATE=advisory`,
`MSCODEBASE_PY=C:\Python314\python.EXE`, `MSCODEBASE_PROJECT_PATH=D:/Project/_m4runs/run1`,
`PYTHONUTF8=1`, `NO_COLOR=1`. Exit **0**. Wall **850.1 s**. Session `ses_eecfa45fdffeVDtohKAMS8wjfW`.
Agent committed `15ea26c0` via `--no-verify` after repo pre-commit gate-zero failed.
**No advisory note text anywhere in the transcript.**
C-plant: `gate_telemetry.jsonl` absent in run data dir AND repo-wide → gate never evaluated.
Root cause (`opencode.log`): `failed to load plugin
path=file:///D:/Project/_m4runs/run1/.opencode/plugin/mscodebase_gate.ts
error="Plugin export is not a function"` (3× — deterministic). opencode ≥1.16 `getLegacyPlugins`
throws on the first non-function export — ours was `export const ROW_REQUIRED_KEYS`
(`.opencode/plugin/mscodebase_gate.ts:128`). Fixed in d9725ba4 (→ §A2: fix insufficient).
Delivery-channel failure, not invocation failure; runs 2–6 not spent.

## B2. Setup validated (attempt 1, kept constant)

Worktree from `HEAD 0f887788`; base fixture commit `aada9aac`; staged sha256
`56c6812450a0f6e1c05536756e2b2e0f6cb9f6b43ff7cd149ecb5e51104501c7` (cross-run identity
confirmed by attempt-2 full-hash match). Minimal graph + pre-run CLI check:
`base: cached, removed_last_caller: 1, deliver: ✓, strikes: 0` in 142 ms.
`MSCODEBASE_PROJECT_PATH` REQUIRED (self-index guard mis-resolves otherwise: wrong tree,
`removed_last_caller: 0`). `MSCODEBASE_PY` required. Voice lengths then: V0=181, V1=220,
V2=155, V3=155 → V1 vs V2 29.5% apart, outside ±10% (fixed by Amendment A1 → §A3).

## B3. Friction findings (attempt 1, still standing)

- **F-a (agent-reported, NOT independently verified):** repo pre-commit gate-zero failed the
  agent's first commit (`4 failed, 2070 passed`), forcing a ~10 min pytest investigation and a
  `--no-verify` commit. Budget ~850 s/run (≈7 h for 30, not 2–4 h) unless triaged.
- **F-b (verified):** the agent's pytest runs built a 19 MB `graph.db` into the run's data dir,
  clobbering the minimal plant graph mid-run — post-fix, a mid-run full-index rewrite before
  the agent's commit is a confound to control (or pin). First-commit-attempt telemetry still
  satisfies C-plant (gate fires pre-pytest), but the final-commit evaluation may go quiet.
- **F-c (verified):** `git worktree prune` removed 3 dead admin entries (shared `.git`
  metadata side effect, reported).

## B4. Leaks / near-misses (attempt 1)

No push; no third-party prose; `frozen/` untouched; no operator commits to shared history.
Data-dir residue left in place with paths recorded (since R2-purged for attempt 2, §A3).

(End of file)
