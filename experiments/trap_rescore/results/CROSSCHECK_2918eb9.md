# CROSSCHECK — independent recomputation from raw rows (no call to his analysis code)

Requirement: recompute the per-task mean difference **myself** from the raw JSONL
and confirm the same number. Deterministic only; no LLM call anywhere.

## 0. What "independent" means here, precisely

| component | his code | my path | independent? |
|---|---|---|---|
| row validity rule | `lablib.row_invalid_reason` (his excerpt) | re-transcribed from the documented rule into my own function | yes — and **cross-checked against his**: 0 mismatches over all 448 rows |
| dedup / banking | `banked()` | my own `banked()` (sort by `ts`, first `(task,arm,rep)` wins) | yes |
| rate accumulation | `rates()` | my own `rates()` | yes |
| per-task difference | `deltas()` | my own `deltas()` | yes |
| **point estimate** | `sum(deltas)/n` | my own | **fully independent — no shared code** |
| **bootstrap CI** | `boot()`, `random.Random(seed)` | re-implemented from the documented spec (task-cluster percentile bootstrap, B=10 000, seed 20261005 / 20250217) | same *algorithm*, written independently. Reproducing the CI bit-for-bit **requires** matching his RNG draw sequence and percentile index rule — that is a spec property, not shared code. Stated so the agreement is not oversold. |

The point estimates — the actual headline numbers — are the part that does not
depend on his RNG at all, and they agree to 10 decimal places.

## 1. Validity-rule cross-check

My transcription of the rule vs the shipped `lablib.py`, compared row by row on
every banked row in all three runs files:

```
validity-rule cross-check: 0 mismatches over 448 rows
```

So any disagreement below could not be blamed on a differing definition of "void".

## 2. Result — AGREE, exactly

```
=== E1 primary: helpful-refuse - sham-refuse, hit | approach, 95% ===
POINT  = -0.3055555556  -> -0.3056
CI95   = [-0.5000000000, -0.1111111111] -> [-0.5, -0.1111]

=== E2 C3 (Model B): helpful-refuse - sham-refuse, Bonferroni 98.33%, 11 tasks ===
POINT  = -0.5454545455  -> -0.5455
CI     = [-0.8484848485, -0.2727272727] -> [-0.8485, -0.2727]  level=0.9833
```

| quantity | his code | my independent path | delta |
|---|---|---|---|
| E1 point | -0.3056 | -0.3055555556 | 0 (identical to 10 dp) |
| E1 CI | [-0.5, -0.1111] | [-0.5000000000, -0.1111111111] | 0 |
| E2 C3 point | -0.5455 | -0.5454545455 | 0 |
| E2 C3 CI | [-0.8485, -0.2727] | [-0.8484848485, -0.2727272727] | 0 |
| E2 C3 n_tasks | 11 | 11 | 0 |
| E2 C3 ci_level | 0.9833 | 0.9833 (`1 - 0.05/3`) | 0 |

**No disagreement found. This is a negative result and I am reporting it as one:**
two independently written paths over the same published rows land on bit-identical
numbers. Nothing here is a "the fixture agrees with itself" result — the point
estimates were computed by code that shares no line with his.

## 3. Arithmetic transparency (both numbers are exactly representable)

Both are simple rationals, which is a useful sanity check on the bootstrap:

- E1: per-task deltas are all in {0, -1/3, -2/3, -1}; the 12 non-zero-free sum is
  `-11/3`, so point = `-11/36` = `-0.30555…`. Exact.
- E2 C3: the 11 per-task deltas sum to `-6`, so point = `-6/11` = `-0.54545…`.
  Exact.
- Both CI endpoints are exact bootstrap quantiles with denominator 36 (`-18/36`,
  `-4/36`) and 11 (`-9.333/11` -> `-28/33 = -0.84848…`, `-3/11 = -0.27272…`).

So the published 4-dp figures are not a rounding artefact of an under-sampled
bootstrap: they are the exact values of the estimator, correctly rounded.

## 4. Per-task detail actually computed by my path

E1 primary (`helpful - sham`, hit|approach), 12 tasks:

```
t1a 0.000000   t3a -0.666667   t5a  0.000000   t10a  0.000000
t14a 0.000000  t16a -0.666667  t18a -1.000000  t19a  0.000000
t21a 0.000000  t22a -0.333333  t24a -0.666667  t26a -0.333333
```

E2 C3 (`helpful - sham`, Model B), 11 tasks:

```
t3a -0.666667  t5a  0.000000  t10a  0.000000  t14a -0.333333
t16a -0.333333 t18a -0.666667 t19a -1.000000  t21a -1.000000
t22a -1.000000 t24a -1.000000 t26a  0.000000
```

Both sets match his scripts' `per_task` blocks line for line.

## 5. Independence caveat I am obliged to state

The rows I read are **his** rows. Agreement proves the *analysis* is faithfully
reproducible from the *published* inputs. It does **not** independently establish
that those rows faithfully record what the agents did — that would require the
per-run transcripts, which are not shipped (see `REDERIVE_2918eb9.md` §6). Two
independent recomputations over one dataset cannot detect an error that happened
upstream of the dataset. That boundary is unchanged by this result.