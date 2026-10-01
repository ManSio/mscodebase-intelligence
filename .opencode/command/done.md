---
description: Close a task honestly — what is verified, what is not, and what stays open
---

You are running the DONE phase. The value of this phase is entirely in what it
refuses to claim.

## Before claiming done

```bash
python tools/verification/run_all.py
python -m pytest tests/ -q
git status --short
```

A green suite does not mean the task is done. It means the guards still work.

## The honesty rules

- **Every number needs a referent**: a command, a path, an id, a hash. A number you
  cannot regenerate today is `measured on <sha>, superseded by X` — not restated.
- **`✅` requires saying where it was verified.** `✅ verified on origin/main`,
  `⚠️ committed, not pushed`, `⚠️ changed, not runtime-tested`, `❓ reported, not
  confirmed`. Pick one; there is no unmarked ✅.
- **List what is still open.** An honest "3 of 9 open" beats a false "done".
- **If something was reverted, say so and why.** Side effects of your own operations
  do not stay silently in the diff.
- **Do not soften a refutation into a partial win.** If the hypothesis failed, say it
  failed.

## Output

```
## [🏁 ИТОГ] <task>
1. What changed (2-4 lines, verbs)
2. Hypothesis / command / raw output / verdict
3. Files changed, and why each
4. Pitfalls hit
5. Numbers: measured by <command>, or "not measured"
6. DoD: what is closed, what is not
7. Verified from clean state: yes/no + how
8. Open items
9. How to check it yourself
```

## Final check

If the honest version of this report is uncomfortable, that is the correct version.
A completion report is the last place where overclaiming is still possible, and
therefore the first place a future reader will look to decide whether to trust you.
