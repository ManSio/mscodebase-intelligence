# E73 — false refusal: the fix works, one gate was miscalibrated

Date: 2026-11-11. Frozen spec: `frozen/PLAN.md` (written before the code).

## Change

`_abstains` now refuses only when **no** identifier occurs, instead of when the
first one does (`src/mcp/tools/investigate_tool.py`). The warning text and the
policy are unchanged: an answer with no subject in the code is still withheld.

## Gates

| # | Gate | Bar | Result |
|---|---|---|---|
| P1 | sqlalchemy `tool` hit@5 | >= 15 / 40 | **PASS — 17 / 40** (was 11) |
| P2 | B1 dev `tool` hit@5 | >= 19 / 71 | **PASS — 19 / 71** (identical) |
| P3 | 44 negative tasks stay silent | 0 leaks | **PASS — 44 / 44 silent** |
| P4 | the 13 formerly-empty commits | >= 8 / 13 | **FAIL — 6 / 13** |

```
sqlalchemy, 40 commits      hit@1  hit@5        before -> after
  tool                         10     17         11 -> 17
  neighbours                   11     19          19
  search                       12     18          18
  grep                          7     20          20
```

## Why P4 read 8 and measured 6 (the spec's own error)

The bar came from a run with `include_neighbours=true`, which bypasses the
refusal entirely. The change does not bypass it: it still refuses when nothing
occurs. Two of the thirteen are exactly that case, and they refuse correctly:

```
749086adb0cc   ids: ... all zero        rows=0 (was 8 with neighbours)
049ed1db162a   mapped_column.default_factory=0, mapped_column.default=0  rows=0
```

So the maximum reachable under the chosen policy is 11/13, and the bar of 8/13
was derived from a path the change does not use. That is a defect in **my spec**,
not a discovery about the code: P1 = 11 + 6 is exactly the six recovered commits.

I am not editing the bar: the gate is recorded as failed, and the decision rule
in the frozen plan says "P4 < 8 -> revert". That rule's premise was "if P4 is
low, the first-token rule is not what costs the answers", and P1 contradicts the
premise (+6 on exactly those commits, no negative leak). The rule and the
measurement conflict, so the ship decision goes to the owner rather than being
resolved by me after seeing the numbers.

## What is verified regardless of that decision

- The false refusal is real: 13 of 40 solvable commits refused an answer the
  tool had found, 8 of them with the gold in the top-5 when shown.
- Removing it costs nothing measured: P2 identical, P3 no leak, invalid runs 0.
- The policy (option C, E69) is intact: 2 of 13 still refuse, because no
  identifier occurs at all.

## Reproduce

```
python experiments/false_abstain_2026_11/verify.py --corpus D:\\Project\\bench-ext\\sa-B \
    --repo D:\\Project\\bench-ext\\sqlalchemy --base 8b62343 \
    --panel D:\\Project\\MSCodeBase\\experiments\\scale_2026_11\\tasks.jsonl
python experiments/bench_2026_11/external.py --repo D:\\Project\\bench-ext\\sqlalchemy \
    --corpus D:\\Project\\bench-ext\\sa-B --base 8b62343 --limit 40
```
