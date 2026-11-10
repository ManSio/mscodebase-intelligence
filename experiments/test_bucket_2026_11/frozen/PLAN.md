# Test-bucket classification — frozen plan (before the code change)

Date: 2026-11-10. Source: `experiments/scale_2026_11/REDTEAM.md` A2.

**Bug.** `_bucket_penalty` treats any `test_*.py` as a test file and subtracts
2.0 from its rows on a code question. `src/core/test_impact.py` is a production
module (it *predicts* test impact), so all its definitions are pushed out of the
answer: three tasks of the E66 panel fail because of it, and grep finds them.

**Change.** The path rule stays, and a content check overrides it: a `test_*.py`
outside `tests/` counts as a test only if it defines `def test_*` or imports
pytest/unittest. Unknown/unreadable files keep the old (penalise) behaviour, so
nothing becomes *more* permissive by accident.

Measured: 926 tracked `.py` files; 271 match the path regex; 260 carry test
markers; **1** production module is misclassified.

## Arms

One binary, `MSCODEBASE_TEST_BUCKET`:

- `path` — shipped behaviour (default; no change until the measurement says so);
- `content` — the override described above.

## Panel

The change can only affect rows whose file matches `test_*.py`, and exactly one
such file is outside `tests/`. So the panel is:

- the 3 affected E66 tasks (`risk_level`, `module_of`, `referenced_modules`);
- the 41 anchors (regression);
- 40 random positives from the E66 panel (regression).

84 tasks x 3 repeats, per-task majority, both arms interleaved.

## Predictions (frozen)

| # | Prediction | Falsifier |
|---|---|---|
| T1 | `content` fixes all 3 affected tasks (`any@8` true) | any of the 3 still misses |
| T2 | no anchor loses `top1` or `any` | any loss |
| T3 | the 40 sampled positives do not lose | any loss |
| T4 | per-task rows are identical between arms on tasks whose files do not match `test_*.py` | any difference |

T4 is the guard against a scalar change leaking into unrelated ranking.

## Kill

T2 or T3 fails -> keep `path` (the shipped behaviour) and record the bug as a
KNOWN_ISSUE instead of a fix. T1 failing means the hypothesis is wrong about the
cause, not about the penalty.

## Note on what this is not

This is a **classification fix**, not ranking tuning. The bar is "the same
answers, plus the three that a production module was losing"; it is not allowed
to reorder the corpus. If it does, T4 trips.
