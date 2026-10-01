---
description: Turn an incident into a guard that prevents its class, not just its instance
---

You are running the POST-MORTEM phase. A post-mortem that produces only a narrative
has failed — its output must be something that fires next time.

## Structure

1. **Symptom** — what was observed, in terms someone else would recognise. Not what
   you think caused it.
2. **Root cause** — the specific line, value, or assumption. "The regex was not
   anchored" beats "regexes are fragile".
3. **Why it survived** — the check that should have caught it, and why it did not.
   This is the part that generalises.
4. **Fix** — with the commit sha.
5. **Guard** — the thing that now fails. A guard is code that runs. "Be more careful"
   is not a guard.
6. **Class** — the family this belongs to. If the family already has an entry, add
   to it; do not create a parallel one.

## Rules

- **One entry per incident, ≤15 lines.** No stack traces, no raw pytest dumps. A
  diary nobody reads protects nothing.
- **The guard ships in the same change as the fix.** A fix without a guard is a
  coincidence waiting to be undone.
- **Check the registry before writing.** A repeated class gets a stronger guard, not
  a new note.
- **Record what you got wrong in the diagnosis.** Self-correction is the most
  reusable part of the entry.

## Sweep for the class

After the guard is in place, ask: where else does this pattern exist? Report
`N of M` and how many distinct idioms. A rule applied in one place and not two lines
later proves the rule was known and not followed — a different problem from not
knowing it.

## Output

```
## [YYYY-MM-DD] <name> — Status
**Symptom:** ...
**Root cause:** <file:line>
**Why it survived:** ...
**Fix:** <sha>
**Guard:** <what now fails, and where>
**Class:** P-### / new class
**Class sweep:** N of M places, K idioms
```
