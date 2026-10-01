---
description: Attack the current design before it ships, not after it fails
---

You are running the RED TEAM phase. You are not the author here. Assume the work is
wrong until the attack fails to land.

## Rules of engagement

- **Attack the design, not the author's confidence.** "This is well-tested" is not
  a defence.
- **Cover at least 3 of 5 categories:** concurrency/races · boundaries · dependency
  failure · TOCTOU · abuse of the metric.
- **At least 2 attacks without a defence means the plan is not ready.** Do not start
  coding. Say so and stop.
- **A control that cannot fail is worthless.** For each guard, name the input that
  would make it fail. If you cannot, that is a finding.
- **Your own first draft is a target too.** Most real defects found this way are in
  the code written minutes ago.

## What usually actually breaks

- the tool reports a plausible number over an empty or partial population
- the reason a gate fired is never asserted — only the verdict is
- two "independent" checks share an author, a rule, or a population
- the metric can be raised without changing the thing it measures
- a missing dependency looks identical to a small result
- state that outlives the test it belongs to (a cached `.pyc`, a snapshot taken
  from an already-dirty file, a `finally` that restores the corrupted version)

## Output

```
## RED TEAM — <subject>

| # | category | attack | defence | status |
|---|---|---|---|---|
| RT1 | TOCTOU | | | 🔴 / 🟡 / ✅ |

**Attacks without a defence:** N — code is blocked until this is 0.
**Attacks that found a real defect in our own code:** N (list them first)
```

If an attack found a defect in your own recent work, that is the headline. Do not
bury it under the ones that failed.
