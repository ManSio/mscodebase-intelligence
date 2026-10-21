# tinycalc — frozen synthetic corpus

Small Python package with two planted defects:

- `tinycalc.core.mean` returns the sum instead of the arithmetic mean.
- Money formatting truncates rather than rounding half up, and `format_total` does not use `round_money`.

Public tests are in `tests/test_public.py`. They are expected to fail before the tasks are solved.
`tests/test_smoke.py` must always pass and is used by preflight.

Do not edit `tests/` during the experiment. Hidden evaluation tests live outside the worktree.
