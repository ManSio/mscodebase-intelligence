# P1 — arithmetic mean

## Goal

Fix `tinycalc.core.mean` so it returns the arithmetic mean of the input values.

Requirements:

- `mean([2, 4, 6]) == 4`
- `mean([1, 2]) == 1.5`
- `mean([])` raises `ValueError`
- `mean([0]) == 0`

## Scope

- Allowed files: `tinycalc/core.py`.
- Do not edit tests.
- Do not add dependencies.

## Acceptance

```text
python -m pytest tests/test_public.py::test_mean_basic -q
```

## Hidden evaluation

`frozen/hidden/test_p1_hidden.py` is not visible to the agent.
