# REDTEAM-M4 — red team on the M4 design, before any run (2026-10-06)

Six attacks. Two land fully and change the harness; the rest are contained by existing controls.

## R1 — Post-commit advisory conflates obedience with independent discovery (PARTLY LANDS)

The note arrives AFTER the commit attempt, so "the final commit contains the fix" scores the same
for an agent that obeyed the note and one that noticed the orphan on retry. The contrast V1−C1
(not raw V1) is the effect, and C1 exists for exactly this. But with n=3 the baseline is noise —
so the smoke estimates nothing and must be labeled an instrument check only: rig runs, gate fires
every run, cost/time measured, no leaks. Zero verdicts from smoke.

## R2 — Restraint state leaks between runs (LANDS → harness fix required)

Restraint (cooldown/strikes) persists per project data dir. Runs sharing a project would get
suppressed notes in later runs — arms would differ by execution order, not voice. **Fix, mandatory:**
every run gets its own project copy (separate worktree → separate data-dir hash → separate state)
AND its own session id; C-plant (gate fired) is checked per run and non-firing runs are discarded,
not scored. Verified in the smoke manifest, not assumed.

## R3 — V1 vs V2 confounds specificity with mood (PARTLY LANDS → label + decompose)

V1 names file:line AND is imperative; V2 is generic AND hedged. A V1 win cannot say which did it.
Contained by V0 (neutral + names the symbol): V0-vs-V1 isolates mood given specificity. The
headline V1−V2 stays composite and must be labeled as such in every future verdict.

## R4 — N=3/arm cannot confirm anything (LANDS → scope the smoke)

Any 95% interval on 3+3 reps straddles zero by construction. Smoke answers only: does the rig run
end to end? does C-plant hold 6/6? what do 6 runs cost and take? are there leaks? Anything beyond
that from smoke is fabrication.

## R5 — Length: V1 is inherently longer than V2 (contained, must be enforced)

V1 names file:line; V2 does not. Controls: ±10% matching measured at run time + V3 filler arm +
decision rule requires V3−C1 null. If lengths fall outside ±10%, the run still counts for the
instrument check but the contrast is marked length-confounded.

## R6 — Leakage: planted break must not escape; no pushes; keys (LANDS → explicit steps)

Per-run worktree under `D:\Project\_m4runs\run<N>` (outside every repo tree, disposable by design);
origin removed from the clone so push is impossible, not merely forbidden; worktrees deleted after
recording; model API use is the same as any normal session. Planted break identical in every run
(same diff, verified by hash before each run).

## Harness amendment (not a change to frozen DESIGN)

To deliver fixed voices through the real channel, the plugin gains `MSCODEBASE_ADVISORY_TEXT`:
when set, non-empty, isolation in advisory mode, and findings > 0, the appended note uses this
text instead of gate output (real output still logged with an override flag). Default unset =
byte-identical behavior. Additive, default-off, test-covered. Amended here, not in frozen files.
