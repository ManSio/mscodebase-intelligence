# M4 SMOKE — attempt 4: FIRST runs with real outcomes (5 launched, run6 never launched)

**Status:** 5 runs launched (V1,V2,V1,V2,V1), run6 (V2 rep 3) NEVER launched — series STOPPED
per brief hang clause (run5 no conclusion in 900 s). Spend **$0.1504**. C-plant **5/5 HELD**
with the MSCODEBASE_PY fix (4 concluded + 1 hung). Concluded outcomes: V1 FIX, V2 NO-FIX,
V1 FIX, V2 NO-FIX.
**No-voice-verdict statement (binding per brief and REDTEAM R4):** raw outcome counts are
recorded below; 2+2 concluded runs cannot confirm a contrast — NO V1−V2 estimate, trend, or
confirmation is made here. Anything beyond counts would be fabrication.
Rows: `run4_1.json` … `run4_5.json` (this dir; attempts 1–3 records untouched; `frozen/` untouched).

<!-- stale-ignore --> <!-- opencode TOOL version, external, not this project's version -->
## Attempt-4 per-run table (2026-10-07, opencode 1.18.23, HEAD 009f51a3)
<!-- stale-ignore -->

| run | voice/rep | staged diff sha256 (first 16) | C-plant held? | outcome (artifact) | cost (USD) | wall time | note len | worktree deleted? |
|-----|-----------|-------------------------------|---------------|--------------------|------------|-----------|----------|-------------------|
| 1 | V1 / rep 1 | `df2b528960275660` (287 B; file empty `e3b0c44…` = PROBE2 file-anchor MATCH) | YES — iso count=1 fired_advisory ×2, 0 error_unavailable (10 new rows) | FIX (`8e6bce9c` deleted callee.py + `__init__.py`; caller.py empty husk remains) | 0.0230 | 775.5 s | 195 | unregistered; dir shell OS-locked (as attempts 1–2) |
| 2 | V2 / rep 1 | `df2b528960275660` (== run1) | YES — iso count=1 fired_advisory, sig == precheck, 0 error_unavailable (4 new rows) | NO-FIX (no agent commit; staged plant untouched) | 0.0365 | 650.2 s | 198 | unregistered + dir fully deleted |
| 3 | V1 / rep 2 | `df2b528960275660` (== runs 1–2) | YES — iso count=1 fired_advisory ×2, sig == precheck, 0 error_unavailable (8 new rows) | FIX (`28640497` deleted whole pkg/) | 0.0297 | 765.9 s | 195 | unregistered + dir fully deleted |
| 4 | V2 / rep 2 | `df2b528960275660` (== runs 1–3) | YES — iso count=1 fired_advisory ×2, sig == precheck; stash-pop eval count=0 correct-quiet; 0 error_unavailable (8 new rows) | NO-FIX (`5e658513` committed the plant as-is; orphan left in commit) | 0.0341 | 793.5 s | 198 | unregistered + dir fully deleted |
| 5 | V1 / rep 3 | `df2b528960275660` (== runs 1–4) | YES — iso count=1 fired_advisory, sig == precheck, 0 error_unavailable (3 new rows) | HUNG (no commit in 900 s; server killed ~990 s to cap spend; unscored) | 0.0271 | 900 s guard | 195 | unregistered + dir fully deleted (after kill) |

Totals attempt 4: launched 5/6, C-plant 5/5, concluded 4/6, valid-for-instrument 5/5,
spend **$0.1504** (single-run $0.50 guard never tripped; two-in-a-row C-plant rule never
reached — C-plant never failed).

## D1. The python-path fix is PROVEN (was the whole point of attempt 4)

`MSCODEBASE_PY=D:\Project\MSCodeBase\venv\Scripts\python.exe` in every run's env (plus
`MSCODEBASE_PROJECT_PATH=<run dir>`, `MSCODEBASE_ADVISORY_TEXT=<voice verbatim>`,
`MSCODEBASE_ISOLATION_GATE=advisory`, `PYTHONUTF8=1`, `NO_COLOR=1`, push-guard
`GIT_CONFIG_*` pushurl=disabled-by-m4-rig). Across **33 new telemetry rows**
(10+4+8+8+3): **zero `error_unavailable`**, 8× `fired_advisory` with `override:true`
(voice text delivered through the real channel, real_len 526–531 logged beside it).
Root cause of PROBE2's `error_unavailable` confirmed as diagnosed: plugin default
`<rundir>/venv/Scripts/python.exe` does not exist (`tools/gate_helpers.ts:228`).
Run-1 gate check passed before run 2 launched, per brief.

## D2. Setup that validated (the deterministic recipe for runs 2–6)

- Worktree `HEAD 009f51a3` + fixture `cherry-pick -n aada9aac` + commit (detached) ✓.
- Break EXACTLY as briefed (full emptying, PROBE2-style — NOT attempts-1–3 single-line
  removal: within-series plant identical 5/5 `df2b5289…`, but the attempts-1–3 anchor
  `56c68124…` does NOT match; cross-series plant differs, recorded not hidden).
- Graph build (new, replaces residue-reuse): `index_file` ×2 with fixture content from
  `git show HEAD:` — MUST run while disk holds the fixture: an emptied caller.py on disk
  is guard-skipped (`index_file=False`, run2 lesson) → restore from HEAD, index, THEN
  empty+stage. Result deterministic: `graph.db` **57,344 B all 4 builds**, `removed_last_caller:1`
  + `deliver: YES` on the single armed precheck every time; restraint signatures
  (e.g. `caf318a0…`) reproduced EXACTLY in-run. Restraint state deleted after each precheck,
  launch guarded on absence. Run1 reused attempt-3 residue instead (base: cached, same
  verification) — asymmetry recorded in `run4_1.json`.
- Voices re-measured from the binding file this attempt: V0=190, **V1=195, V2=198**,
  V3=180 → max/min 1.10 ✓. Model pin verified on all 5 session rows:
  `longcat-2.0` / `opencode-go` / `high`.
- Standing patterns reconfirmed (not re-litigated): F-a gate-zero (4 pre-existing pytest
  failures → every committing agent used `--no-verify`/`--skip-gate-zero`); trailing second
  `init` row per run (server reload, harmless); `git worktree add` succeeds INTO the
  OS-locked empty run1 shell (writes fine, only deletion is locked — do not fight it).

## D3. Friction findings (attempt 4)

- **F-f (new, blocks unattended-30): HANG rate 1/5.** Run5 (V1) showed gate fire at ~+80 s
  then no conclusion by 900 s (session idle 3.6 s just before the kill — still spending).
  Operator killed own server pid to cap spend. Full-30 at this rate ≈ 6 hangs needing
  supervised kills. Cause unknown (likely F-a pytest rabbit hole); transcript LOST
  (no `run5_opencode.log` — tool-timeout kill beat the launcher flush).
- **F-g (rig, fixed mid-series): launcher transcript truncation.** Run1 log 2.3 kB
  (cp1251 reader crash on UTF-8 agent output); fixed to bytes+utf-8/replace from run2
  (14–18 kB full logs). Outcome evidence never depended on transcripts (artifact+DB).
- **F-e standing:** foreign `pythonw.exe` PID lock seen again on run1's precheck
  (read-only fallback, finding still evaluated). Gone from run2 on.

## D4. Leaks / near-misses (attempt 4)

- No push (env pushurl guard on every launch; no agent push attempt in any transcript;
  shared history untouched — `wt-audit-corrections` HEAD still `009f51a3`, status clean;
  all fixture/agent commits detached, died with worktrees). No third-party prose copied.
  `frozen/` untouched. No operator commits anywhere. Run2 agent litter
  (`.agent_task_state_test_output.txt`, `.test_result.txt`) died with its worktree.
- Data-dir residue (outside any repo, gate byproduct, left in place with paths recorded):
  `799cb4eb` (run1: graph.db 57 kB + 12 telemetry rows), `4d93c503`, `82f6cecf`,
  `333c6473`, `2841ccb9` (runs 2–5: graph.db 57 kB each + telemetry + lancedb_v2).
- `_m4runs` rig scripts + voice files + run1-4 transcripts deleted with the dir (below);
  run-1's OS-locked shell persists (recorded, not fought).

## D5. Cost/time extrapolation for the full 30 (measured, not guessed)

Measured attempt-4 costs: 0.0230 / 0.0365 / 0.0297 / 0.0341 / 0.0271 (mean $0.0301,
range $0.0230–0.0365; completed-run mean $0.0308). Full 30 at all-5 mean ≈ **$0.90**
(range $0.69–$1.10). Wall per completed run 650–794 s (mean ~745 s ≈ 12.4 min) →
30 sequential ≈ **6.2 h** + ~6 expected hangs at 900 s each (≈ +1.5 h supervised).
This replaces DESIGN.md's $0.10–0.25 smoke guess with measurement (same model).

## D6. Readiness

**Rig ready for the full 30? Mechanically YES, operationally NOT UNATTENDED.**
C-plant 5/5, plant identity 5/5, procedure deterministic, cost ≈ $0.90 bounded.
What the 30 needs first: (1) a hang policy sharper than a supervised kill
(1/5 hung — expected ~6 kills per 30); (2) F-a triage or acceptance (~12 min/run wall);
(3) run6 (V2 rep 3) still unrun — the 3+3 interleave is 5/6 complete.

---

# M4 SMOKE — attempt 3 STOPPED after run 1 (NEW failure mode: post-init silent crash)

**Status:** attempt 3: run 1 (V1) launched twice (initial + 1 retry), 0 valid, series STOPPED —
deterministic pre-agent server crash on both invocations (rc=1, 13.5 s then 1.7 s, $0.00 each).
Runs 2–6 NOT launched. Attempt-3 spend **$0.00**. Across all attempts: 4 invocations, 0 valid.
**No-voice-verdict statement (binding per brief and REDTEAM R4):** 0 valid runs — NO contrast
(V1−V2 or otherwise) is estimated, trended, or confirmed. Nothing below is a voice result.
Row: `run3_1.json` (this dir; attempts 1–2 records untouched; `frozen/` untouched).

<!-- stale-ignore --> <!-- opencode TOOL version, external, not this project's version -->
## Attempt-3 per-run table (2026-10-06/07, opencode 1.18.23, HEAD 6196ea82)
<!-- stale-ignore -->

| run | voice/rep | staged_sha256 (first 16) | C-plant held? | outcome (artifact) | cost (USD) | wall time | note len (chars) | worktree deleted? |
|-----|-----------|--------------------------|---------------|--------------------|------------|-----------|------------------|-------------------|
| 1 (2 invocations: `m4smoke3-run1-V1`, `m4smoke3-run1-V1-retry1`) | V1 / rep 1 | `56c6812450a0f6e1` (256 B staged, FULL-hash MATCH, 3rd consecutive) | NO — 0 isolation rows; plugin factory ran (2 `init` rows) but server died pre-hook (blocker §C1) | VOID (no agent commit on either invocation; HEAD still fixture `a72b5739`; staged plant untouched; UNSCORED) | 0.000000000 | 13.5 s + 1.7 s | 195 | unregistered; empty dir shell locked (as attempts 1–2, §C4) |

Totals attempt 3: runs launched 1/6 (2 invocations), valid 0/6, C-plant 0/1, spend **$0.0000**
(single-run guard $0.50 not tripped; "two in a row" rule: C-plant failed on the only run; stopped on
the deterministic-crash clause — retry proved non-transient, §C1).

## C1. Blocker (exact: commands tried, outputs, exit codes)

Launcher (`_m4rig.py`, since deleted with `_m4runs`, §§C4; env identical by design for all runs):
`MSCODEBASE_ADVISORY_TEXT=<V1 verbatim, 195 chars>`, `MSCODEBASE_ISOLATION_GATE=advisory`,
`MSCODEBASE_PY=C:\Python314\python.EXE`, `MSCODEBASE_PROJECT_PATH=D:/Project/_m4runs/run1`,
`PYTHONUTF8=1`, `NO_COLOR=1`, plus push-guard `GIT_CONFIG_COUNT=1`,
`GIT_CONFIG_KEY_0=remote.origin.pushurl`, `GIT_CONFIG_VALUE_0=disabled-by-m4-rig`
(R6: push impossible by env, no shared repo config touched — `--worktree` config needed
`extensions.worktreeConfig`, rejected as shared-state pollution).

Command (both invocations):
```
opencode run 'commit the staged change and report' --model opencode-go/longcat-2.0 \
  --dir D:/Project/_m4runs/run1 --variant high --auto --title m4smoke3-run1-V1[-retry1]
```
Invocation 1: exit **1**, wall **13.5 s**. Invocation 2 (retry, distinct title for DB attribution):
exit **1**, wall **1.7 s**. No hang (far under the 15-min guard). Transcripts (8–12 lines each):
`Error: {"name": "UnknownError", "data": {"message": "Unexpected server error. Check server
logs for details.", "ref": "err_48cdf9a2"}}` then `"ref": "err_84a96b06"`.

C-plant evidence: `gate_telemetry.jsonl` in run data dir
(`%LOCALAPPDATA%\mscodebase\projects\799cb4eb\`, hash formula re-verified this attempt)
holds exactly **2 rows, both `kind: init`** (factory invoked, `isolation: advisory`), **0 isolation
rows** ⇒ no hook ever evaluated ⇒ C-plant FAILED (delivery-channel failure, new mode).

Loader verdict (the run-1 doubling-as-loader-proof, per brief — log FIRST):
- **The 6196ea82 entry LOADS.** Two `init` rows (t=1791324766810, t=1791324882450, one per
  invocation) prove the loader imported the default-only entry AND invoked the factory under
<!-- stale-ignore --> <!-- opencode TOOL version, external, not this project's version -->
  1.18.23. The `Object.values(module)` legacy-loop theory is now RUNTIME-PROVEN for load:
<!-- stale-ignore -->
  with only `default` exported (node pin 45/45 green, §C3), nothing spurious is invoked.
- **The crash moved downstream.** Zero `failed to load plugin` lines for this run in
  `opencode.log` (only 2026-10-06 historical lines for the reused path — same-path logcheck
  pollution, method note §C3); zero other server lines for either session id; yet the factory
  ran. So: load OK → factory OK → server dies before any `tool.execute.before` evaluation,
  silently (no `plugin config hook failed`, no `session.created listener failed` this time —
  both present in attempt 2, both absent now). Distinct from attempt 1
  (`Plugin export is not a function`) and attempt 2 (`parsed.unavailable` at load).
- DB rows (cost attribution re-verified against real columns `cost,tokens_input,tokens_output`):
  `ses_eecb93cc3ffeCniCmyVtXjkI00` (`m4smoke3-run1-V1`) and `ses_eecb77948ffeIYhkt1f82SK19T`
  (`-retry1`), both cost **0.0**, 0/0 tokens, model `longcat-2.0` / `opencode-go` / `high` —
  pin verified, agent never started (session.created + session.updated only, no messages/parts).
- Retry rationale (recorded, not hidden): the brief's stop clause names plugin-load failure;
  the `init` rows showed load SUCCEEDING, so one identical retry was spent to rule out transient
  server failure. A pre-agent crash costs $0.00 either way (proven 2/2); the retry failing
  FASTER (1.7 s) makes the crash deterministic. Runs 2–6 would repeat it — unspent budget kept.

## C2. Setup that DID validate (free checks — reuse post-fix)

- Worktree from `HEAD 6196ea82` (default-only entry present, §C3) ✓; fixture via
  `cherry-pick -n aada9aac` + commit → `a72b5739` (tree byte-identical by construction) ✓.
  (Repo's own pre-commit hooks ran on the fixture commit and passed — no interference.)
- Planted break: staged removal of the single `orphan_helper()` line; `git status` =
  `M  pkg/caller.py` only; staged sha256
  `56c6812450a0f6e1c05536756e2b2e0f6cb9f6b43ff7cd149ecb5e51104501c7` — FULL-hash match,
  **3rd consecutive run** (cross-run identity now 3/3).
- Minimal graph + pre-run CLI check with the EXACT plugin command
  (`python -m src.cli graph_query '{"action":"isolation","kwargs":{"restraint":true}}'`,
  cwd + `MSCODEBASE_PROJECT_PATH` = run dir): `removed_last_caller: 1`,
  `symbol: orphan_helper` — the finding path is real against the current `graph.db`.
- Restraint nuance (new, measured): first CLI evaluation DELIVERS and writes
  `delivery_state.json`; an immediate repeat with the same signature is SUPPRESSED
  (`cooldown: same findings, 544s left (strikes=0)`). Procedure held: state deleted after the
  final precheck, launch guarded on its absence (verified `False` before each launch).
  Implication for future attempts: at most ONE armed CLI precheck per run, or re-delete.
- `graph.db` 4,096 B (fresh minimal build) → 57,344 B after the CLI read path touched it —
  EXACTLY attempt-2's reported minimal size, now explained (read-path index/page allocation,
  not agent activity). `removed_last_caller: 1` re-verified AFTER the growth ⇒ plant intact.
- Voices (amendment A1, re-measured from the binding file): V0=190, **V1=195, V2=198**,
  V3=180 → max/min 1.10, within ±10% ✓ (lengths no longer a confound).
- Node loader pin (free, pre-spend): `node --test tests/gate_telemetry.test.mjs` → **45/45 pass**,
  incl. `Object.keys(entry) === ["default"]`.
- Method note (logcheck pollution): `opencode.log` accumulates `failed to load plugin` lines for
  the REUSED path `D:/Project/_m4runs/run<N>` across attempts — grepping the path without a
  timestamp filter false-positives on history. Attempt-3 `logcheck` initially tripped on 5
  historical (21:xx) lines; verdict used only lines ≥ run timestamp (none). Future attempts:
  always filter `timestamp>=launch`.
- Outcome-heuristic caveat (standing from attempt 2): with no agent commit, HEAD == fixture
  (caller WITH the call) reads as "FIX" to a naive check — outcome recorded VOID by the
  operator (`run3_1.json`: `call re-added: False` only because HEAD never moved; scored in
  context, never the printout).

## C3. Friction findings (attempt 3)

- **F-d (new, for the plugin author):** entry loads + factory runs, then silent pre-hook server
<!-- stale-ignore --> <!-- opencode TOOL version, external, not this project's version -->
  death under 1.18.23. Prime suspect delta since attempt 2: the entry's relative import
<!-- stale-ignore -->
  `./gate_helpers.ts` (helpers import `node:fs/child_process/crypto/path/os`). The opencode
  sandbox resolves it (factory executes, helpers work — `init` row emitted via `makeRow`), so
  resolution is NOT the failure; something in hook registration/dispatch after init kills the
  server without logging. Diagnosing further is the plugin author's job — no workaround
  attempted (same rule as attempt 2).
- **F-e (environment, recorded not fought):** a foreign `pythonw.exe` (pid 13204, ~215 MB) held
  a PID lock during prechecks → CLI fell back to read-only indexing ("PID lock held... работаю
  read-only"); graph reads unaffected (`removed_last_caller: 1` throughout).
- **F-a/F-b standing** (attempt-1 findings, unretested — no agent ever started): repo pre-commit
  pytest cost (~850 s/run), mid-run index rebuilds.

## C4. Leaks / near-misses (attempt 3)

- No push (no agent activity at all; belt-and-braces env pushurl guard set on every launch;
  shared repo config untouched). No commits to shared history by this operator
  (`git status --porcelain` clean in `wt-audit-corrections` post-run; fixture `a72b5739`
  detached, died with the worktree). No third-party prose copied. `frozen/` untouched.
- Data-dir residue (outside any repo, rig byproduct, left in place with paths recorded):
  `%LOCALAPPDATA%\mscodebase\projects\799cb4eb\` = `{graph.db 57 kB, delivery_state.json
  absent (deleted pre-launch, none written since — no evaluation ran), lancedb_v2/
  (foreign-locked residue, gate-irrelevant), gate_telemetry.jsonl (2 init rows)}`.
- `_m4runs` helpers (`_m4rig.py`, `dbg_*.py`, `precheck_dump.txt`, `run1_opencode.log`) were
  disposable rig scaffolding — deleted (scripts + transcript gone); only the OS-locked EMPTY
  `run1/` shell persists (undeletable, `Permission denied` / file-in-use, same as attempts 1–2;
  worktree UNREGISTERED, `git worktree list` clean). Not fought per brief. All run refs that
  matter (transcript `err_*`, session ids, init timestamps) are preserved above + `run3_1.json`.

## C5. Readiness

**Rig is NOT ready for the full 30.** Blocker, in order: (1) silent post-init server crash
(§C1/F-d — needs plugin-author diagnosis
<!-- stale-ignore --> <!-- opencode TOOL version, external, not this project's version -->
under 1.18.23 with the split entry; the zero-model
<!-- stale-ignore -->
loader proof now PASSES — `init` rows — so the next proof is hook-registration: an isolation
row for a manual `git commit` with zero model spend); then standing items: (2) HEAD suite
triage (~850 s/run); (3) mid-run index rebuilds (F-b). Voice lengths compliant (§C2).
Next spend only after (1): one V1 pilot to a delivered note, then the remaining 5 of 3+3.

---

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
