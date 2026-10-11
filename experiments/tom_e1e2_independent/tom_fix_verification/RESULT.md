# Independent confirmation of Tom's key-matching fix (2026-10-11)

Tom pushed the input-validation fix in crystal-memory@7a129db (parent 491f385) and
tjonesit/crystals@b86edc7 (parent 2918eb9) — both change `scripts/crystal_act.py`
(+45/−5) and add `CHANGELOG-2026-10-10.md`, crediting "Found by Mikhail (@ManSio)".

We re-ran OUR five audited false-fires and the normalization strings against HIS OWN
functions (`matches_ctx`, `match_scope`, `normalize_match`) loaded straight from both
revisions (raw.githubusercontent), no model, $0 — `verify_tom_fix.py`.

| case | kind | OLD 491f385 | NEW 7a129db | expected |
|------|------|-------------|-------------|----------|
| cargo vs escargot | false-fire | fires | silent | fire then fix |
| \|tail vs log\|tailspin | false-fire | fires | silent | fire then fix |
| \|head vs cmd\|headache | false-fire | fires | silent | fire then fix |
| \|grep vs cmd\|grepable | false-fire | fires | silent | fire then fix |
| <<eof vs <<EOFILE | false-fire | fires | silent | fire then fix |
| cargo vs "cargo build" | legit | fires | fires | keep |
| \|tail vs "log \|tail -n 5" | legit | fires | fires | keep |
| <<eof vs real heredoc | legit | fires | fires | keep |
| post- vs POST-notes.md | prefix | fires | fires | keep |
| post- vs repost-notes.md | prefix | fires | silent | no fire |
| ssh vs zero-width | normalize | silent | fires | fix |
| ssh vs cyrillic dze | normalize | silent | fires | fix |
| ssh vs fullwidth | normalize | silent | fires | fix |
| git status vs nbsp | normalize | silent | fires | fix |
| git status vs thin space | normalize | silent | fires | fix |

**Result: 15/15, failures 0 → TOMS-FIX-INDEPENDENTLY-CONFIRMED.**

- The OLD revision is the control that must fail: it reproduces the length-5 hole 5/5.
- The NEW revision closes all five; the three real commands still fire; `post-` still
  prefix-matches and does not fire as a suffix of `repost-`; all five normalization
  inputs now match.
- Confirmed against his shipped code, not his description.

Boundary (not covered here): his scale numbers (cross-host, methodology only); his
"100 real acts" replay (needs his acts); the Claude Code hook→agent loop (his
territory). Our strings slice the fix we audited; a full regression across his key
inventory is his selftest's job.
