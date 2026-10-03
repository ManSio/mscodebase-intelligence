---
description: Run one hypothesis with a control, raw output, and a verdict
---

You are running the EXPERIMENT phase. A measurement without a control is a story.

## Before running

1. **Write the hypothesis and what would refute it.** Not "test if X is faster" —
   "X is faster than Y when Z, and I will be wrong if the median difference is under
   10ms".
2. **Freeze the input** into `experiments/<name>/frozen/` with a sha256, BEFORE you
   look at any result. If you edit the list after seeing the outcome, the result is
   indistinguishable from hindsight.
3. **Decide the control now.** Every experiment needs a case that MUST FAIL. An
   instrument that has never been seen to fail has not been shown to work.
4. **Record reproducibility parameters explicitly in the command**, never by
   default: seed, temperature, reasoning budget, model version, variant. A decision
   made earlier in this session that never made it into the command line did not
   happen.

## While running

- Capture **raw output**, not a summary. If the run printed 3 lines, keep all 3.
- If the population is empty, the answer is "undeterminable", not 0. An empty input
  is a different state from a measured zero and must look different on the way out.
- If something fails once, do not retry with the same parameters. Change the
  hypothesis or the method, and say which.

## Afterwards

1. **Recompute from the raw data.** Do not read your own previous verdict back as
   input. Recompute, then compare.
2. **Run the gates**:
   ```bash
   python tools/verification/gates.py --gate population --input '{"population": N, "computed_rate": R}'
   python tools/verification/run_all.py
   ```
3. **Held-out or not?** Replaying on the case where the bug was found is
   `✅ confirmed on known case`, never generalization. Mark it exactly.
4. **Count the denominator.** "Fixed 3 places" is meaningless. Report `N of M`, and
   how many distinct idioms.

## Output

```
## EXP-<n> — <hypothesis>
**Command:** <exact, copy-pasteable>
**Raw output:** <verbatim, or the path to the frozen file>

**Result:** ...
**Verdict:** CONFIRMED | REFUTED | PARTIAL | HELD-OUT CONFIRMED | UNKNOWN
**Gates:** G1 <verdict> · G2 <verdict> · G4 <verdict>
**Population:** N of M, selected by <rule>
**Negative control:** failed as required — <raw>
```

Never write `✅` without saying where it was verified.
