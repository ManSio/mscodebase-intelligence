# E73 — the first-token abstain is a false refusal (frozen plan)

Date: 2026-11-11. Written before the code change.

## Root cause (Verified by reading the code and the answers)

`src/mcp/tools/investigate_tool.py:138` (`_abstains`) decides "the subject does
not occur" from **the first identifier in the extraction order**:

```python
subject = next(iter(per))
return per.get(subject) == 0 and not known
```

On 13 of the 40 solvable sqlalchemy commits that token is prose, a dotted
annotation or a type name, and its count is 0 while the next identifier occurs
hundreds of times:

```
f1693787ade6  ids: _orm.relationship.primaryjoin, omit_join, relationships
              exact: _orm.relationship.primaryjoin=0, omit_join=47
049ed1db162a  ids: mapped_column.default_factory, mapped_column.default, ...
              exact: mapped_column.default_factory=0, mapped_column.default=0
6165193fb3f4  ids: _orm.registry, Declarative, MetaData
              exact: _orm.registry=0, Declarative=785
```

The answer is then emptied (`results: 0`, `verdict: abstain (0.00) — subject does
not occur and the graph does not know it`) although the tool found the rows.
With `include_neighbours=true` the gold file is in the top-5 for **8 of the 13**.

Measured: **13 of 40** solvable commits abstain (32.5%); grep answers 20/40, the
tool 11/40 — 11 + 8 = 19, which is where the gap actually is.

This is not the owner's policy (option C, E69). The policy says "refuse when the
question has no subject in the code". The code says "refuse when the first
extracted word is absent". Only the second is a bug.

## Change under test

`_abstains` abstains only when **no** identifier occurs:

```python
return not known and not any(count > 0 for count in per.values())
```

`_format` keeps its "⚠️ exact: the first identifier does not occur … neighbours"
warning only for the same case (nothing occurs); otherwise the neutral
`exact:` line is printed. That keeps the message consistent with the verdict.

## Bar (frozen, all four)

| # | Gate | Pass |
|---|---|---|
| P1 | sqlalchemy `tool` hit@5 | **>= 15 / 40** (from 11) |
| P2 | B1 dev `tool` hit@5 | **>= 19 / 71** (no loss) |
| P3 | 44 negative tasks (`where is zz_<hex> defined`) | **0 answers with rows** (no leak) |
| P4 | the 13 formerly-empty commits | **>= 8 / 13** put the gold in top-5 |

P3 uses `experiments/scale_2026_11/tasks.jsonl`, `kind == "negative"` — the same
list that was measured at 40/40 before (E66).

## Decision rule

- All four pass -> ship the fix.
- P1 < 15 or P4 < 8 -> the first-token rule is not what costs the answers;
  revert to the shipped condition and record the negative result.
- P2 < 19 -> fresh regression on the calibrated corpus: stop and investigate
  before shipping, even if P1 passes.

## What would invalidate this

- Editing the bar after seeing a number.
- Reporting P1 without P3: a fix that answers negatives is a false-positive
  generator, and that is worse than the false refusal.
- Choosing the 13 commits by hand: they are the IDs printed by
  `count_empty.py` on the fixed 40-task list.
