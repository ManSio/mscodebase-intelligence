# PREREG_CHECK — locked rules vs implemented rules

Scope: bundle files `prereg/*.md` (the locks) vs
`prereg/analysis-code/analyse_e1.py`, `analyse_e2.py` (the implementation).
Method: full read of all four files in scratch; pure-statistical functions
executed (`boot_mean`/`classify`, `boot`/`classify`/`deltas`) — these need no
harness. Row-validity logic (`valid_rows`/`banked` → `lablib.row_invalid_reason`)
could NOT be checked: `lablib` is not in the bundle (see REDERIVE.md).

## 1. What was locked, at which lock commits (as stated in bundle README)

- E1 design (AMENDMENT 1), whole-doc file locked 2026-10-03 @ source-repo
  commit `372d76af` ("locked two days before E1 ran"). Only later change
  before E1 runs stated as a framing note at the top of the section
  (`21c99b49`); "no design value, threshold or rule changed" (claim).
- E2 design (AMENDMENT 2), whole-doc file locked 2026-10-05 12:04 @
  `b92088de` ("locked before any E2 note, arm or run existed; E2 started
  19 minutes later").
- Analysis code commits (claims): `analyse_e1.py` @ `96cb9f92` "committed
  before any E1 outcome was read"; `analyse_e2.py` @ `28aa66cd` "committed
  before E2 started".
- Source-repo commits (`372d76af`, `b92088de`, `96cb9f92`, `28aa66cd`,
  result `54cbcb19`, scorer `3aa07223`, …) live in the PRIVATE source repo:
  spot-checked `54cbcb19` and `372d76af` against `tjonesit/crystals` via API —
  not found there (HTTP 422), as expected. Their timestamps/order are
  UNVERIFIABLE from this bundle alone.

## 2. Amendment 1 (E1) — locked rules

- Design: 12 qualifying traps × 3 reps × 3 arms (NONE, SHAM, HELPFUL) = 108
  runs; contingency (<12 / <8 qualifying traps) specified.
- Primary estimand: per-task conditional hit rate per arm
  (hits-among-approaching / approaching); task contrast
  Δt = HELPFUL − SHAM; estimand = unweighted task-cluster mean of Δt.
  Tasks with zero approaching runs in HELPFUL or SHAM are EXCLUDED, count
  reported. Approach-rate compromise flag: |approach_H − approach_S| > 0.15
  with HELPFUL approaching less.
- Inference: 95% percentile task-cluster bootstrap CI, 10,000 resamples
  (tasks with replacement, all arm data carried).
- Decision thresholds: SUPPORT iff CI entirely below 0 AND upper ≤ −0.05;
  NO EFFECT iff CI entirely within [−0.05, +0.05]; else INCONCLUSIVE.
  Classification by CI alone; point-estimate branch rule (Δ ≥ 0 → "content
  not doing work") only gates downstream experiments.
- Multiplicity: ONE confirmatory contrast (HELPFUL vs SHAM, hit|approached).
  Raw hit rate and adoption H-vs-S are secondary; everything else exploratory.
- Voids/re-runs: peeked or infra-failed runs void + re-run in same cell,
  max two replacements, then missing (no imputation). No interim looks.
  Refusal-first channel fixed (§8), single-channel rule with stratification
  fallback.

## 3. Amendment 2 (E2) — what it changed/added

- Design: Model A (Sonnet 5) NONE/HELPFUL/SHAM/FACT/MOVE/FIRM-GENERIC × 12
  traps × 3 reps (216); Model B (Haiku 4.5) NONE/HELPFUL/SHAM × 12 × 3 (108).
  Same channel; notes length-matched within 10%.
- Confirmatory family of THREE: C1 HELPFUL-vs-FACT (A), C2 HELPFUL-vs-MOVE
  (A), C3 HELPFUL-vs-SHAM (B). Bonferroni: per-contrast CI level
  1 − 0.05/3 = 98.33%. All else exploratory at unadjusted 95%, no labels.
- Estimation: percentile task-cluster bootstrap, B = 10,000, seed 20250217
  for every contrast. SUPPORT: U ≤ −0.05. NO EFFECT: L > −0.05, U < +0.05,
  L < 0. Else INCONCLUSIVE ("compatible with harm" noted when L ≥ 0).
  Fewer than 6 valid tasks → "not estimable" (inconclusive).
- Model B inclusion filter: drop tasks whose Model B NONE arm has < 2
  approached runs; < 6 survivors → C3 not estimable. Replication rule:
  C3 SUPPORT → replicates; NO EFFECT → does not; INCONCLUSIVE → undetermined.
- Approach-imbalance diagnostic: flag task-arm pairs whose approach proportion
  differs from the task across-arm mean by > 0.40 (arms with ≥ 1 completed
  run); reported only, never decisional.

## 4. Implementation check — file:line evidence

E1 (`analyse_e1.py`): bootstrap `boot_mean` lines 79–90 (B=10,000 line 32,
seed 20261005 line 31; percentile indices 249 / 9749 of 10,000 = 2.5%/97.5%,
verified by execution); exclusion of either-side-zero-approach tasks
`per_task_delta` lines 67–76; thresholds `classify` lines 93–100
(SUPPORT `hi <= -0.05`; NO EFFECT `lo >= -0.05 and hi <= 0.05`); compromise
flag line 131 (`> 0.15` and HELPFUL less); branch rule line 137
(`delta >= 0`); single confirmatory + secondary/exploratory split lines
126–143. Executed edge checks: `classify(-0.5,-0.06)=SUPPORT`,
`classify(-0.05,0.05)=NO EFFECT`, `classify(-0.2,0.01)=INCONCLUSIVE`,
`classify(-0.2,-0.049)=INCONCLUSIVE` — all match §3 including boundary values.

E2 (`analyse_e2.py`): level `CONF_LEVEL = 1 - 0.05/3` line 30 (=
0.98333…, reported rounded 0.9833 line 134); B/seed line 29
(`SEED, B = 20250217, 10000`); bootstrap `boot` lines 71–77 (tail-index math
83 / 9916 verified by execution — a genuine 98.33% percentile interval, and
the file's own selftest asserts it is at least as wide as the 95% one);
thresholds `classify` lines 80–85; <6 → NOT ESTIMABLE lines 91–93;
Model B filter `ap >= 2` line 119; replication mapping line 121;
imbalance `> 0.40`, arms with ≥1 run, lines 101–112; exploratory contrasts
at 0.95 unlabeled lines 123–126. Executed: `classify(-0.04,0.04)=NO EFFECT`,
`classify(-0.2,-0.05)=SUPPORT`, `classify(0.0,0.03)=INCONCLUSIVE (compatible
with harm)` — match §3.2; `deltas` skips non-NA-violating tasks correctly.

Resampling note (both files): the code resamples precomputed task-level Δt
rather than resampling tasks then recomputing rates from run rows. For the
locked estimand (unweighted mean of task deltas, deterministic in task data)
these are the same distribution — implementation-equivalent, not a deviation.

## 5. Verdict

**No deviations found** between the locked decision rules (§§2–4 of amendment
1; §§1–5 of amendment 2) and the analysis code, on every part inspectable
from this bundle. Two observations (not deviations — the lock text does not
pin these choices):

1. E1 secondary adoption is computed as adoption/all-runs
   (`contrast(banked, H, S, "adoption", False)`, line 139), not
   adoption|approach. Amendment 1 §4 names the contrast but not the
   denominator, so either is lock-compliant; flagging so a re-analyst does
   not assume conditional adoption.
2. E1 "approach rates … summarized similarly" (amendment §2) is implemented
   as point rates without bootstrap CIs (`approach_rates`, lines 114–123).
   The confirmatory decision does not use them; the word "similarly" is
   ambiguous, so this is not scored as a deviation.

Uncheckable from the bundle: whether `lablib.row_invalid_reason` (void/peek
logic, called `analyse_e1.py:38,41` and `analyse_e2.py:35,39`) implements
amendment §§5 exactly — `lablib.py` is absent (see REDERIVE.md missing list).
Also uncheckable: lock timestamps/ordering (all source-repo commits) and the
"committed before outcomes were read" claims — no timestamps survive in
bundle files.
