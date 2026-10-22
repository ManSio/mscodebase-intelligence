# P2 — money rounding and formatting

## Goal

Fix money handling so totals are rounded half up to two decimal places and
`format_total` uses the shared `round_money` helper.

Requirements:

- `round_money("1.005") == Decimal("1.01")`
- `format_total([("1.005", 1)]) == "$1.01"`
- `format_total([("0.105", 2)]) == "$0.21"`
- `format_total([("0.00", 5)]) == "$0.00"`
- `format_total([("0.10", 3)]) == "$0.30"`

## Scope

- Allowed files: `tinycalc/core.py`, `tinycalc/formatting.py`.
- This is a parent task for the microtask arm: the planner must split it into
  two one-file microtasks with a dependency.
- Do not edit tests.
- Do not add dependencies.

## Acceptance

```text
python -m pytest tests/test_public.py::test_total_half_up -q
```

## Hidden evaluation

`frozen/hidden/test_p2_hidden.py` is not visible to the agent.
