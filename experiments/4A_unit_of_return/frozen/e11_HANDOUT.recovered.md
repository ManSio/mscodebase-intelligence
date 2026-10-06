# E11 handout — frozen list vs the NEW arrival index (blind)

Instruction: For **each** numbered item, pick **one** entry from the catalogue that best explains it, or `NONE` if none fits. Do not force a match. Answer as a table: `# -> entry`. Answer from the text only; do not use tools, search, or MCP.

## Items

1. All tests pass, but when I open the app and click the button, nothing happens.
2. Background reindex shows ETA "~8s" and progress freezes at "Finalizing".
3. Postgres replication lag grows linearly under write load.
4. I deleted an entire function and the test suite stayed green.
5. CI is red on ruff errors that are only caught after push.
6. My GPU driver crashes when the batch size exceeds 64.
7. Hung `git cat-file` processes; `git.exe`/`conhost` chains multiply; RAM climbs.
8. `lock_guard` raises `ThreadExpired`: timeout 60s < pre-commit duration 5-10 min.
9. I compared my new build against my old one and the numbers were identical, so I said the change did nothing.
10. A test is green but `MagicMock.embedding_dim` is truthy.
11. The CSS grid collapses only in Safari 17.
12. `drift_gate` is a false negative: the control never fired on real drift.
13. `verify-on-read` retracts true facts (false-retraction).
14. The TESTS signal ranks tests but does not improve answer quality.
15. Tests fail locally but pass in CI (after clearing `__pycache__`).
16. My coding agent won't use my high-level code-intelligence tools; it keeps reaching for raw grep instead.

## Catalogue

### Arrival index — start here if you do not yet know the cause

Find the sentence closest to the one you would actually say.

| What you would say | Family | Entry |
| --- | --- | --- |
| my agent won't use the tools I set up | A | a-component-that-needs-starting-passes-every-behaviour-test |
| all the checks are green and the screen is blank | A | a-component-that-needs-starting-passes-every-behaviour-test |
| it said the tests passed and the app is still broken | A | a-component-that-needs-starting-passes-every-behaviour-test |
| build succeeded and the thing won't even start | A | a-component-that-needs-starting-passes-every-behaviour-test |
| the suite is all passing and I can still reproduce the crash | A | a-component-that-needs-starting-passes-every-behaviour-test |
| the first call works and every call after that does nothing | A | a-component-that-needs-starting-passes-every-behaviour-test |
| I don't trust this green check | A | a-guard-keyed-on-a-field-nobody-fills-is-a-silent-no-op |
| my agent is being lazy and not checking anything | A | a-guard-keyed-on-a-field-nobody-fills-is-a-silent-no-op |
| this coverage number can't be right | C | a-rate-knob-cannot-fix-a-denominator |
| same prompt as last time and now it fails | C | a-single-run-ranking-is-noise-even-at-temp-zero |
| it works in one chat and fails in the other with the same prompt | C | a-single-run-ranking-is-noise-even-at-temp-zero |
| it works on the first try and fails when I rerun it | C | a-single-run-ranking-is-noise-even-at-temp-zero |
| I don't believe these benchmark numbers | C | a-single-run-ranking-is-noise-even-at-temp-zero |
| the PR page says passing and the job log says failed | C | an-instrument-that-answers-a-different-question-can-be-wrong-two-ways |
| the UI shows success and the terminal shows an error | C | an-instrument-that-answers-a-different-question-can-be-wrong-two-ways |
| CI is green and production is down | C | an-instrument-that-answers-a-different-question-can-be-wrong-two-ways |
| it times out every time I try this | D | a-cached-429-is-not-a-rate-limit |
| these numbers jumped overnight and I don't buy it | D | a-number-that-moves-without-new-data-is-an-assumption |
| this pass rate looks too good to be true | D | a-number-that-moves-without-new-data-is-an-assumption |
| these timings look way too perfect | D | a-number-that-moves-without-new-data-is-an-assumption |
| i just opened it and still has spacing issues and looks like nothing was done | E | a-generated-document-is-unverified-until-you-render-it |
| the coverletter seemed to be in a different file format and did not work | E | a-generated-document-is-unverified-until-you-render-it |
| the README examples don't match what I get when I run it | E | a-generated-document-is-unverified-until-you-render-it |
| it works on my machine but CI is red | E | an-instrument-that-reshapes-input-fabricates-the-test |
| it works for me and not for my teammate | E | an-instrument-that-reshapes-input-fabricates-the-test |

NOTE: 3 of 12 entries have no arrival sentence at all: a-surviving-mutant-can-mean-the-code-is-dead, a-control-built-from-the-treated-arm-is-not-a-control, testing-rejection-is-not-testing-immutability.

### Symptom index — the instrument-side names for the same failures

Family A:
- The whole suite is green and the shipped binary draws an empty box -> a-component-that-needs-starting-passes-every-behaviour-test
- A guard has never fired and I assume that means things are fine -> a-guard-keyed-on-a-field-nobody-fills-is-a-silent-no-op
- I deleted the code on purpose and the test still passed -> a-surviving-mutant-can-mean-the-code-is-dead

Family B:
- My before and after look identical, so the change did nothing -> a-control-built-from-the-treated-arm-is-not-a-control
- My immutability test passes and the operation still edits the caller's copy -> testing-rejection-is-not-testing-immutability

Family C:
- I turned the sampling rate all the way up and almost nothing was sampled -> a-rate-knob-cannot-fix-a-denominator
- My benchmark ranking flipped between two identical runs -> a-single-run-ranking-is-noise-even-at-temp-zero
- Two tools share the same rule and give me different answers -> an-instrument-that-answers-a-different-question-can-be-wrong-two-ways

Family D:
- I am being rate limited, and backing off does not help -> a-cached-429-is-not-a-rate-limit
- A figure is correct and its premise is dead -> a-number-that-moves-without-new-data-is-an-assumption

Family E:
- The file validates and the output still looks wrong -> a-generated-document-is-unverified-until-you-render-it
- My test harness reports bugs that do not reproduce by hand -> an-instrument-that-reshapes-input-fabricates-the-test
