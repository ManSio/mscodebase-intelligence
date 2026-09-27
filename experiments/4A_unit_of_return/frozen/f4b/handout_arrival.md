# F4b HANDOUT — condition: ARRIVAL index (blind)

Instruction: For **each** numbered item, pick **one** entry from the index below that best explains it, or `NONE` if none fits. Do not force a match. Answer as a table: `# -> entry`. Answer from the text only; do not use tools, search, or MCP.

## Items

1. Repeated identical queries were answered straight from the cache without ever executing the dense retrieval stage.
2. A sandboxed user script could read the host process's API keys and tokens out of its environment.
3. It keeps timing out every time I retry, no matter what.
4. When two threads resolved the same service concurrently, two independent instances were created (e.g. two graph objects on one database).
5. The Kubernetes pod keeps getting OOM-killed on the node.
6. A tool's own docstring warned that sandboxing was absent, contradicting the strict sandbox the code actually ran.
7. The clean-state CI job died with exit 127 on the Linux runner because it invoked `.exe` paths that do not exist there.
8. I set the sample-rate knob to its maximum and still almost nothing was captured.
9. After a timeout, the project's latency metrics showed negative values, corrupting min_ms, avg_ms, P50/P95.
10. The database schema migration locked the table for an hour.
11. A Cypher query asking for paths up to five hops silently returned only the direct neighbours instead of the deeper chain.
12. Running the Zed settings cleanup erased every JSONC comment the user had written in settings.json.
13. Two runs of the same benchmark gave opposite rankings.
14. The Docker image build fails because the base image tag was removed.

## Arrival index (what you would say -> entry)

| What you would say | Entry |
| --- | --- |
| my agent won't use the tools I set up | a-component-that-needs-starting-passes-every-behaviour-test |
| all the checks are green and the screen is blank | a-component-that-needs-starting-passes-every-behaviour-test |
| it said the tests passed and the app is still broken | a-component-that-needs-starting-passes-every-behaviour-test |
| build succeeded and the thing won't even start | a-component-that-needs-starting-passes-every-behaviour-test |
| the suite is all passing and I can still reproduce the crash | a-component-that-needs-starting-passes-every-behaviour-test |
| the first call works and every call after that does nothing | a-component-that-needs-starting-passes-every-behaviour-test |
| I don't trust this green check | a-guard-keyed-on-a-field-nobody-fills-is-a-silent-no-op |
| my agent is being lazy and not checking anything | a-guard-keyed-on-a-field-nobody-fills-is-a-silent-no-op |
| this coverage number can't be right | a-rate-knob-cannot-fix-a-denominator |
| same prompt as last time and now it fails | a-single-run-ranking-is-noise-even-at-temp-zero |
| it works in one chat and fails in the other with the same prompt | a-single-run-ranking-is-noise-even-at-temp-zero |
| it works on the first try and fails when I rerun it | a-single-run-ranking-is-noise-even-at-temp-zero |
| I don't believe these benchmark numbers | a-single-run-ranking-is-noise-even-at-temp-zero |
| the PR page says passing and the job log says failed | an-instrument-that-answers-a-different-question-can-be-wrong-two-ways |
| the UI shows success and the terminal shows an error | an-instrument-that-answers-a-different-question-can-be-wrong-two-ways |
| CI is green and production is down | an-instrument-that-answers-a-different-question-can-be-wrong-two-ways |
| it times out every time I try this | a-cached-429-is-not-a-rate-limit |
| these numbers jumped overnight and I don't buy it | a-number-that-moves-without-new-data-is-an-assumption |
| this pass rate looks too good to be true | a-number-that-moves-without-new-data-is-an-assumption |
| these timings look way too perfect | a-number-that-moves-without-new-data-is-an-assumption |
| i just opened it and still has spacing issues and looks like nothing was done | a-generated-document-is-unverified-until-you-render-it |
| the coverletter seemed to be in a different file format and did not work | a-generated-document-is-unverified-until-you-render-it |
| the README examples don't match what I get when I run it | a-generated-document-is-unverified-until-you-render-it |
| it works on my machine but CI is red | an-instrument-that-reshapes-input-fabricates-the-test |
| it works for me and not for my teammate | an-instrument-that-reshapes-input-fabricates-the-test |
