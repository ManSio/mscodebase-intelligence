---
description: Audit published numbers or a guard against a derived denominator
---

You are running the AUDIT phase. The target is not the code — it is the
**confidence** of a number someone might believe.

## The trap this exists to prevent

A hand-written list of items makes its own contents eligible by definition. The
denominator becomes an assertion dressed as a measurement, and a number built that
way can only ever return 100%. Derive the population; never author it.

## Order of work

1. **Derive the population by scanning.** A rule that finds candidates, applied to
   every artifact that carries claims. Print the rule next to the count.
2. **Separate two different questions.** `n_found` is derived by the machine;
   `n_reviewed` is authored and starts at 0. Merging them makes coverage 100% by
   construction.
3. **Triage every finding, by hand.** Automated triage was tried twice and both
   attempts were wrong in opposite directions — a keyword scan missed guarded
   files, a division regex cited filesystem paths as rate sites. Read the actual
   line.
4. **Measure the false-positive share.** Until it is measured, the count is not a
   verdict. `N findings` without an FP ratio cannot be published.
5. **Distinguish "wrong" from "dead".** A number that no longer reproduces because
   the path was deleted by design is `SUPERSEDED`, not `FALSE`. Different action.

## After the audit

- Anything that used to be published and no longer reproduces gets a new entry
  naming the old one. Never silently edit a published number.
- Anything unmeasurable now is `CANNOT VERIFY`, not `FALSE`.
- Update the frozen manifest and re-run:
  ```bash
  python tools/verification/bootstrap_denominator_manifest.py
  python tools/verification/g5_denominator.py
  ```

## Output

```
## AUDIT — <subject>
**Population:** N derived by <rule>, across <files>
**Triaged:** T true · P partial · F false · U unresolved
**FP share measured:** F/N = <%>

| # | claim | verdict | referent | note |
```

State plainly which numbers a reader should stop trusting.
