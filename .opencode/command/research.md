---
description: Research a protocol, rule, or tool from primary sources before building on it
---

You are running the RESEARCH phase of the protocol. Your only job is to produce
facts the owner can decide on. You are not deciding.

## Order of work

1. **State the question and its falsifier.** "Does X work?" is not a question.
   "Under what condition is X wrong?" is. Write both down before searching.
2. **Search for the primary source, not the summary.** A blog post about a paper is
   not a source. Prefer the paper, the spec, the release notes, the code.
3. **Record the negative result.** A search that returned nothing useful is data.
   Write which query failed and what it should have returned. A quietly wrong search
   result is worse than an empty one — it looks like an answer.
4. **Freeze the input before you look at the result** if this is an experiment
   rather than a reading task. See `experiments/*/frozen/`.
5. **Separate Verified from Recalled.** Anything you did not open in this session is
   Recalled and must be marked so.

## Output

```
## [🔍 ИССЛЕДОВАНИЕ] <subject>

**Question:** ...
**Falsified if:** ...

**Sources**
| source | what it establishes | verified how |

**Negative results**
- query → what it failed to find

**What this changes in our code**
- concrete file:line, or "nothing"

**Still unknown**
- the question this does NOT answer
```

## Rules

- Two contradictory sources: report both, do not average them.
- A claim with a number gets a referent, or it does not go in the report.
- Do not recommend an action. Present options and their costs; the owner decides.
- If the research contradicts something we published, that is the most important
  line in the report. Put it first.
