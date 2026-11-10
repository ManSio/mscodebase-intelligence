# E67 — test-bucket classification

Frozen: `frozen/PLAN.md`. Source: `experiments/scale_2026_11/REDTEAM.md` A2.

## The bug

`_bucket_penalty` treats any `test_*.py` as a test file and subtracts 2.0 from
its rows on a code question. `src/core/test_impact.py` is a production module (it
*predicts* test impact), so its definitions were pushed out of the answer: three
E66 tasks failed there and a plain grep found them.

Blast radius, measured: 926 tracked `.py` files, 271 match the path regex, 260 of
them are real tests (they define `def test_*` or import a test framework), **1**
production module is misclassified.

## Fix

The path rule stays; a content check overrides it outside `tests/`: a `test_*.py`
counts as a test only if it defines tests or imports pytest/unittest. Unreadable
files keep the old (penalise) behaviour, so nothing becomes more permissive by
accident. `MSCODEBASE_TEST_BUCKET=path` restores the previous rule.

## Measurement

Arms: `path` vs `content`, one binary, interleaved. Panel: the 3 affected tasks +
41 anchors + 40 sampled positives, 3 repeats, per-task majority.

```
T1  affected fixed (any@8)            3/3    PASS
T2  anchors not worse                 21/41 vs 21/41   PASS
T3  sampled positives not worse       40/40 vs 40/40   PASS
T4  identical on unrelated tasks      PASS
```

Re-check of the load-bearing claim, 3 repeats per task per arm:

```
path     risk_level / module_of / referenced_modules   (valid, any, top1) x3
         all three: (True, False, False) x3              -> 0/9
content  all three: (True, True, True) x3                -> 9/9
```

One of 504 calls in the full A/B returned an invalid answer (a degraded run); the
majority of 3 covered it, and the targeted re-check above has 18 valid calls.

## Result

The default is now `content`; `path` remains as a rollback via the env var. The
change is a classification fix, not ranking: T3/T4 confirm it does not reorder
anything that does not involve a `test_*.py` file.
