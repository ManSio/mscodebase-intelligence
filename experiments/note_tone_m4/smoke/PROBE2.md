# PROBE2 — single loader probe, helpers OUTSIDE `.opencode/plugin/` (HEAD d292e3a0)

Date: 2026-10-07 ~01:58–02:04 +03:00. Operator: probe session (no commits, no pushes by operator).
Worktree: `D:/Project/_m4probe2` (detached HEAD `b4da09b8` = fixture commit on top of `d292e3a0`).
Break planted by operator: `pkg/callee.py` (`def orphan_helper(): return 42`) + `pkg/caller.py`
calling it, committed as `b4da09b8`, then `pkg/caller.py` emptied and STAGED (uncommitted).
Staged sha256 of emptied `pkg/caller.py`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
(empty file — expected; exact bytes of the anchor were not required to match the old one).

Launch (ONE budgeted run, model `opencode-go/longcat-2.0`, prompt `commit the staged change and report`,
`--title m4probe2-loader`, cwd = run dir):
`opencode run --model opencode-go/longcat-2.0 --title m4probe2-loader 'commit the staged change and report'`
(deviation recorded: no `--dir/--variant/--auto` flags; cwd served as run dir instead of `--dir`).
Env: `MSCODEBASE_PROJECT_PATH=D:/Project/_m4probe2`,
`MSCODEBASE_ISOLATION_GATE=advisory`, `MSCODEBASE_ADVISORY_TEXT=<V1 single-line, spaces where the
frozen file wraps lines>`:
`GRAPH-GATE (advisory): this commit isolates `orphan_helper` (pkg/callee.py) — its last caller in pkg/caller.py is removed. Fix it now: re-add the call or delete the symbol. Do not leave it as is.`
(word sequence identical to `frozen/VOICES_AMENDMENT_A1.md` V1; newlines joined with spaces).
Harness note: the launcher shell reported `Unknown: ChildProcess.kill` immediately, but the run
demonstrably proceeded server-side (session + telemetry + server lines below). No second launch.

## The five answers

1. **`failed to load plugin`? NO.** `opencode.log`
   (`C:\Users\misha\.local\share\opencode\log\opencode.log`), all lines containing
   `_m4probe2` with `timestamp>=2026-10-06T22:58:44Z` (launch 01:58:44+03:00): 0 `level=ERROR`
   lines; 0 genuine `failed to load plugin` lines (the only string match is the operator's own
   later grep command echoed inside a `run=3808fdf5` permission-evaluation line — harness
    session, not the probe).
<!-- stale-ignore --> <!-- verbatim log quote below; opencode TOOL version is external, not this project's version -->
Server-side instance id `27509c14`, opencode `1.18.23`:
    `timestamp=2026-10-06T22:59:06.791Z level=INFO run=27509c14 message=created id=ses_eec8ed258ffewvsSYGFelwLb8L slug=playful-mountain version=1.18.23 projectID=36a532b26162886fc907a08115e93cf8742b83fc directory="D:\\Project\\_m4probe2" path="" workspaceID=undefined parentID=undefined title=m4probe2-loa`
<!-- stale-ignore -->

2. **Gate init rows? YES — 1.** `%LOCALAPPDATA%\mscodebase\projects\9231ca3f\gate_telemetry.jsonl`
   (hash formula re-verified: md5(`d:/project/_m4runs/run1`)[:8] = `799cb4eb`, matches SMOKE.md):
   `{"t":1791327546534,"kind":"init","directory":"D:\\Project\\_m4probe2","stale":"block","isolation":"advisory","log":"C:\\Users\\misha\\AppData\\Local\\mscodebase\\projects\\9231ca3f\\gate_telemetry.jsonl"}`

3. **Server survived past 60 s? YES.** Instance `27509c14` server lines span
   `22:58:56Z` (creating instance) through `23:04:10Z` (last tracking line) — 5+ min of live
   server, incl. watcher backend, project-copy refresh, and per-minute tracking lines. The agent
   consumed 88901 input / 597 output / 547 reasoning tokens (nonzero model activity).

4. **Gate row beyond init? YES — 2 eval rows, same commit action.** The agent attempted
   `bash git commit -m "refactor(probe): remove planted orphan_helper caller probe"` and both
   gates evaluated it (neither delivered — `error_unavailable`, i.e. the finding path errored,
   not the loader):
   `{"t":1791327579495,"gate":"stale","mode":"block","act":"bash git commit -m \"refactor(probe): remove planted orphan_helper caller probe\"","drift":0,"delivered":false,"reason":"error_unavailable","latency_ms":7}`
   `{"t":1791327579497,"gate":"isolation","mode":"advisory","act":"bash git commit -m \"refactor(probe): remove planted orphan_helper caller probe\"","count":0,"delivered":false,"reason":"error_unavailable","latency_ms":1}`

5. **Commit happen? NO.** Post-run: HEAD still `b4da09b8`, `git status` = `M pkg/caller.py`
   staged only, plant untouched. No agent commit exists in the worktree.

## Cost / wall time

Session `ses_eec8ed258ffewvsSYGFelwLb8L` (`m4probe2-loader`, `D:/Project/_m4probe2`,
model `{"id":"longcat-2.0","providerID":"opencode-go","variant":"default"}`):
time_created 1791327546791 → time_updated 1791327850632; cost **0.030272604 USD**;
tokens 88901 in / 597 out / 547 reasoning. Launch 01:58:44+03:00 → last session activity
02:04:10+03:00 ≈ **326 s (~5.4 min)** wall. Data-dir residue (outside any repo, gate byproduct):
`%LOCALAPPDATA%\mscodebase\projects\9231ca3f\` (`gate_telemetry.jsonl` 3 rows, `graph.db` ~18 MB
from a full index build during the run, `progress.json`, `intelligence/`, `lancedb_v2/`,
`metrics/`) — left in place, paths recorded.

## Cleanup

`git worktree remove --force D:/Project/_m4probe2` → REMOVE-EXIT True, `git worktree list`
clean (no `_m4probe2` entry), `Test-Path D:/Project/_m4probe2/` = False — dir fully deleted,
no OS-locked residue this time. Fixture commit `b4da09b8` dies with the worktree; shared history
 untouched (no operator commits, no pushes; `SMOKE.md` and `frozen/` untouched).
