# REDERIVE — both headline numbers re-derived from the banked rows @ `2918eb9`

SUPERSEDES the corresponding verdict in `REDERIVE.md` (§19.11 — the old file is
not edited; its "not re-derivable" finding is superseded by this one).

Deterministic only. **No LLM call was made at any point in this audit.**

## 1. Exact commands (his recipe, `RUNS-AND-FIXTURES.md:18-22`, executed verbatim)

```
cp analysis-deps/lablib.py prereg/analysis-code/
python3 prereg/analysis-code/analyse_e1.py --results runs/e1/results.jsonl
python3 prereg/analysis-code/analyse_e2.py --a runs/e2a/results.jsonl --b runs/e2b/results.jsonl
```

Run from a clean directory holding only those 6 files (Windows, `python` = 3.14):

```
python prereg\analysis-code\analyse_e1.py --results runs\e1\results.jsonl
python prereg\analysis-code\analyse_e2.py --a runs\e2a\results.jsonl --b runs\e2b\results.jsonl
```

Both ran with **no arguments beyond the documented ones**, no defaults overridden,
no seeds touched (`seed` 20261005 / 20250217, `n_boot` 10000 as hard-coded in the
shipped scripts).

## 2. E1 primary — CONFIRMED, exact to 4 dp

| | claimed | re-derived (his code) | re-derived (my independent path) |
|---|---|---|---|
| point estimate | -0.3056 | **-0.3056** | **-0.3055555556** |
| CI lower (95%) | -0.5 | **-0.5** | **-0.5000000000** |
| CI upper (95%) | -0.1111 | **-0.1111** | **-0.1111111111** |
| verdict | SUPPORT | SUPPORT | (lo = -0.5 <= -0.05) |
| n_tasks | 12 | 12 | 12 |

Full-precision from my own aggregation: point `-0.3055555556`, CI
`[-0.5000000000, -0.1111111111]`. Agreement to 10 dp — see
`CROSSCHECK_2918eb9.md`.

Per-task differences (my path, 6 dp), sorted:

```
t1a  0.000000  t3a -0.666667  t5a   0.000000  t10a  0.000000
t14a 0.000000  t16a -0.666667 t18a -1.000000  t19a  0.000000
t21a 0.000000  t22a -0.333333 t24a -0.666667  t26a -0.333333
```

Cross-checks against the rest of his published text:

- "the effect sits in 6 of the 12 traps; no trap got worse"
  (`README.md:15`) — **CONFIRMED**: exactly 6 negative (t3a, t16a, t18a, t22a,
  t24a, t26a), 6 exactly zero, 0 positive.
- SHAM vs no note "+0.03 [-0.14, +0.17]" (`README.md:14`) — **CONFIRMED**:
  re-derived `+0.0278`, CI `[-0.1389, +0.1667]`.

## 3. E2 C3 — CONFIRMED, exact to 4 dp

| | claimed | re-derived (his code) | re-derived (my independent path) |
|---|---|---|---|
| estimate | -0.5455 | **-0.5455** | **-0.5454545455** |
| CI lower | -0.8485 | **-0.8485** | **-0.8484848485** |
| CI upper | -0.2727 | **-0.2727** | **-0.2727272727** |
| ci_level | 0.9833 (Bonferroni, 11 tasks) | 0.9833 | `1 - 0.05/3 = 0.9833…` |
| n_tasks | 11 | 11 | 11 |
| verdict | SUPPORT | SUPPORT | (hi = -0.2727 <= -0.05) |

Also re-derived and matching `README.md:20-21`: C1 = **-0.0556**, CI
`[-0.25, 0.1111]` and C2 = **-0.1111**, CI `[-0.3889, 0.1111]`, both
**INCONCLUSIVE** (CIs cross zero) — his "CIs cross zero" statement is accurate.

### 3a. "11 tasks" — where the 12th went (worth recording, he does not say)

Two different filters, and the number 11 comes from the second, not the first:

1. Model B inclusion filter (`analyse_e2.py:119`): keep tasks whose Model B **NONE**
   arm has >= 2 approached runs -> **12 tasks survive**, reported as
   `model_b.n_included = 12`.
2. `deltas()` (`analyse_e2.py:66`): drop a task unless **both** contrast arms have
   >= 1 approached run -> **`t1a` drops** (its Model B `sham-refuse` arm had zero
   approached runs) -> **11 tasks** enter C3.

So "11 tasks entered the contrast" is correct. The nuance: `t1a` was removed by
arm emptiness, not by the Model B NONE-arm rule that `README.md:18-19` describes
adjacent to it. Not an error — a reader could reasonably assume otherwise.

## 4. Component counts — CONFIRMED, and the 35-vs-36 question resolved

His published framing (`README.md:11-13`): "12 traps x 3 arms x 3 reps = 108 runs.
Pooled: HELPFUL note 18/35 = 0.51 vs SHAM note … 30/35 = 0.86."

Re-derived from the rows (valid rows only, `hit` counted **only when `approach` is
true** — the prereg primary outcome):

| arm | valid runs | approached | hits | rate | his claim |
|---|---|---|---|---|---|
| `helpful-refuse` | 36 | **35** | **18** | 0.5143 | "18/35 = 0.51" — CONFIRMED |
| `sham-refuse`   | 36 | **35** | **30** | 0.8571 | "30/35 = 0.86" — CONFIRMED |
| `none`          | 36 | 36     | 29     | 0.8056 | 29/36 = 0.81 (prior session) — CONFIRMED |

### Is 35 the right denominator given 12 traps x 3 reps?

**Yes — 35 is correct, and 36 would have been wrong for these ratios.** But the two
numbers measure different things, and the gap is *not* caused by the voided rows:

- **36 = the number of runs per arm.** 12 traps x 3 reps = 36, exactly. All three
  arms have 36 valid runs. The 3 peeked voids are excluded *and* their replacements
  retained, so the run count is restored to 36 — verified, not assumed.
- **35 = the number of runs that actually approached the trap.** Exactly one valid
  run per arm failed to approach, so its `hit` is not eligible:
  - `helpful-refuse`: `t5a` rep 2, `approach=False` (`runs/e1/results.jsonl`)
  - `sham-refuse`: `t1a` rep 1, `approach=False`

The primary outcome is *"trap hit **given** the run approached the trap"*, so the
denominator must be approached runs. Reporting 18/36 or 30/36 would have quietly
counted a non-approach as a non-hit and diluted both arms. He did not make that
error.

Note the direction of the bias that the 35 *does* introduce: the two dropped runs
both have `hit=False`, so excluding them slightly *raises* both rates — it does
not manufacture the effect, which is ~0.34 in size.

## 5. Design-integrity checks that passed

- E1 valid rows = 108 = 12 x 3 x 3 exactly; E2a = 216 = 12 x 6 x 3 exactly;
  E2b = 108 = 12 x 3 x 3 exactly.
- No cell exceeds 3 rows after dedup; 36 distinct `(task, arm)` cells in E1.
- Exactly 12 distinct task ids in every runs file, matching `tasks/`
  (`t1a t3a t5a t10a t14a t16a t18a t19a t21a t22a t24a t26a`), no others.
- `approach_check`: helpful 0.972 / sham 0.972, `compromised: false`
  (the two arms were approached at equal rates, so the contrast is not an
  approach-rate artefact).
- `branch_rule_content_not_doing_work: false` (the classification did not key on
  branch-rule content instead of the trap).

## 6. What I did NOT verify (stated, not zeroed)

- **`NOT RE-DERIVABLE: the "380 of 380" approach agreement and "hit agreed on 11 of
  12 traps" N-version claim** (`README.md:65-68`). `scorers/compare_builds.py` and
  `scorers_independent.py` need a `Run` object from the full harness (`lablib`),
  which ships only as the 35-line validity excerpt (`README.md:70-71` states the
  scorers are "here to be read and compared, not executed"). No per-run tool-call
  transcripts ship, so the scorers cannot be re-run. Not checked, not refuted.
- **`NOT RE-DERIVABLE: t5a's cross-check basis.** `README.md:66-68` states t5 could
  not be checked after the fact because per-run files are deleted, and that a later
  re-run with work directories kept gave 6/6. Those per-run files are not in this
  bundle.
- **`NOT CHECKED: result commit `54cbcb19`** (`README.md:15`). It is in the private
  source repository, not in `tjonesit/crystals`; not reachable read-only.
- **`NOT CHECKED: the pre-registration lock commits** (`372d76af`, `b92088de`,
  `96cb9f92`, `28aa66cd`) — private source repository, not in this bundle. Only
  their *content* was read (`PREREG_CHECK.md` from the prior session covers that).