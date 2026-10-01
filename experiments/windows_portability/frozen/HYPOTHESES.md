# WINDOWS-PORTABILITY INVESTIGATION — frozen hypotheses v1

**Frozen:** 2026-09-30, BEFORE reading the relevant code paths for this investigation.
**Object:** `Tirthahq/crystal-memory @ 6cb8479` — FOREIGN repo, read-only. Nothing is edited there.
**Measuring environment:** Windows 11, Python 3.14.3, `locale.getpreferredencoding() = cp1251`, NTFS.
**Declared support of the object:** `INSTALL.md:13` — "Python 3.8 or newer... **macOS or Linux**".

**Freeze rule:** this list is not edited after results are seen. A hypothesis that turns out to be
untestable is marked `CANNOT TEST`, not dropped. New hypotheses require v2 with a new sha256.

**Question per hypothesis:** does this behaviour silently differ on Windows, and if so, does anything
DETECT the difference? A difference alone is a finding. A difference that is *undetected* is the
finding that matters, because the tool speaks into an agent's context.

---

## H-group A — path shape (the class already proven by N3)

| # | Hypothesis | Why suspect | Falsifier |
|---|---|---|---|
| A1 | `os.path.relpath` / `join` emit `\` and that text is delivered verbatim to the agent | N3 already showed one live instance | already CONFIRMED at midflight:169 — carried as control, not re-tested |
| A2 | Hardcoded `/` in compared/delivered strings breaks under `\` | selftests are string equality on paths | grep + a failing-case probe |
| A3 | Glob / `fnmatch` / `rglob` patterns written with `/` match nothing on Windows | `Path("memory/plans")` style | construct the same path both ways |

## H-group B — process boundary

| # | Hypothesis | Why suspect | Falsifier |
|---|---|---|---|
| B1 | `text=True` without `encoding=` decodes by locale; non-ASCII child output raises | 14/14 sites lack `encoding=` (N6) | force a non-ASCII byte through a real call path |
| B2 | `shell=True` resolves to `cmd.exe`, so `sh` builtins silently become "exit 1" | N4 already showed 2 failures + 1 false PASS | CONFIRMED at discriminators:76 — control |
| B3 | Command *strings* in the store (`discriminator:` field) are POSIX-only by data, not by code | the store is user data, so a Windows user can write a Windows-safe one | inspect store format + try a cmd-safe probe |
| B4 | A timeout leaves the child alive (POSIX `shell=True` kills the shell, not grandchildren) | orphan process accumulation is our own incident class | launch a grandchild and see if it survives |
| B5 | Exit-code contract (`0 pass / 1 fail / 2+ cannot-see`) assumes a shell that propagates the child's code | `cmd /c` vs `sh -c` propagation | probe a nested command's exit code |

## H-group C — filesystem semantics

| # | Hypothesis | Why suspect | Falsifier |
|---|---|---|---|
| C1 | Exclusive locking written POSIX-style is a no-op on Windows | `fcntl`/`flock` unavailable; msvcrt needed | find the lock implementation |
| C2 | Atomic write = write-temp-then-`os.replace` fails on Windows if the destination is open | classic | open the target and try the write |
| C3 | `os.utime` / mtime granularity or NTFS timestamp semantics differ from the age test | `MAX_AGE_H=24` window | touch a file and re-read age |
| C4 | `os.walk` includes files the store must not see (hidden/system, or `~` backups) | store is a directory walk | plant a hidden file and see if it is picked up |
| C5 | Reserved names / trailing dots / MAX_PATH break store lookups | Windows filenames | plant a reserved name |
| C6 | `os.path.realpath` / symlink & junction semantics differ; `Path.resolve()` needs the target to exist | Windows junctions vs POSIX symlinks | resolve a dangling link both ways |

## H-group D — time, locale, text

| # | Hypothesis | Why suspect | Falsifier |
|---|---|---|---|
| D1 | `time.strftime` without an explicit encoding/locale is fine, but any `%c`-style format differs | locale is cp1251 | run the exact format calls |
| D2 | `datetime` naive-vs-aware mixing is a code smell independent of platform | — | read the code |
| D3 | A note's own text is read with `errors="replace"` in some places and strict in others — inconsistent | file reads in the sweep showed BOTH | enumerate, count |

## H-group E — the thing the tool is FOR (does Windows change the product's value?)

| # | Hypothesis | Why suspect | Falsifier |
|---|---|---|---|
| E1 | The push mechanism is a shell hook; on Windows the hook never fires → the product is inert, not merely degraded | README says the push is Claude-Code specific | read the hook wiring |
| E2 | Delivery ledger keys on a path string, so the same note under `\` and `/` is two different notes (double-delivery or missed backoff) | ledger is keyed by name | read the ledger key construction |
| E3 | A guard that cannot fail on Windows is worse than no guard, because the store reports it as working | our own `drift_gate` precedent | find any Windows branch of a guard |

## Declared limits BEFORE testing (so they cannot be discovered post-hoc as excuses)

- **L1** The object declares macOS/Linux only. Therefore "fails on Windows" is **not** a product
  regression. The honest claim is: *the boundary of the declared support is invisible from the tool's
  own output* — nothing tells the user "I am out of support".
- **L2** Any difference I find on Windows is **not** evidence about macOS/Linux behaviour. Both may
  work; this machine can only speak about one.
- **L3** Python 3.14 is newer than the declared floor (3.8). A failure here may be a 3.14 change
  rather than a Windows change. Where separable, the experiment must separate them.
- **L4** I cannot run macOS/Linux here, so "would also fail on Linux" is **CANNOT TEST**, never
  asserted from reading.
- **L5** Findings are about the *observed artefact*. The author's intent is out of scope; where the
  code contains a comment claiming a behaviour, the code wins and the disagreement is itself reported.

## Red Team — attacks on MY OWN plan (written before execution)

| Attack | Defence |
|---|---|
| **R1** I will find Windows failures and present them as a critique of his code, when the repo declares macOS/Linux — that is a cheap win and not a contribution | L1 fixes the claim in advance; the deliverable is the *invisible boundary*, not a bug list |
| **R2** "It fails on my machine" — my harness, not his code, could be the cause (already burned once by `PYTHONUTF8=1` in the previous round) | every experiment runs a control that must PASS in the same harness; confounds are separated by explicit regime, as in the CRLF test |
| **R3** Static reading of `shell=True`/paths proves a *possibility*, not a *defect*; a real finding needs the failure to be demonstrated AND undetected | each finding needs a run that produces the wrong result silently, plus a check that nothing reports it |
| **R4** Selecting hypotheses because they are likely to succeed (confirmation bias) — the frozen list must include at least one hypothesis expected to FAIL | H-A2, C1, C5, C6, E2 are expected to be refuted or untestable; they stay in the manifest regardless |
| **R5** Scope creep: a 88 KB `crystal_act.py` invites an open-ended code review that never finishes | the manifest is the boundary. Anything not in it goes to a "not examined" list rather than being silently added |
| **R6** TOCTOU / my own harness mutating the reference clone, so later runs measure a changed artefact | all execution in throwaway copies; the reference clone is verified unchanged (git status clean) at the end |
