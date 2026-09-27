# F4b HANDOUT — condition: SYMPTOM index (blind)

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

## Index (symptom -> entry)

| Symptom | Entry |
| --- | --- |
| The whole suite is green and the shipped binary draws an empty box | a-component-that-needs-starting-passes-every-behaviour-test |
| A guard has never fired and I assume that means things are fine | a-guard-keyed-on-a-field-nobody-fills-is-a-silent-no-op |
| I deleted the code on purpose and the test still passed | a-surviving-mutant-can-mean-the-code-is-dead |
| My check fails and I am sure the fix is wrong | a-check-written-with-the-code-inherits-its-assumptions |
| My before and after look identical, so the change did nothing | a-control-built-from-the-treated-arm-is-not-a-control |
| I checked the judge on an example and it was fine, so the null must be real | one-calibration-pair-is-a-smoke-test-not-a-validation |
| My immutability test passes and the operation still edits the caller's copy | testing-rejection-is-not-testing-immutability |
| Two configurations are being compared and I cannot say what is different between them | a-benchmark-arm-is-its-candidate-pool |
| I got a clean zero and it is telling me to abandon the work | a-failed-lookup-must-not-render-as-a-real-zero |
| I turned the sampling rate all the way up and almost nothing was sampled | a-rate-knob-cannot-fix-a-denominator |
| My benchmark ranking flipped between two identical runs | a-single-run-ranking-is-noise-even-at-temp-zero |
| Two tools share the same rule and give me different answers | an-instrument-that-answers-a-different-question-can-be-wrong-two-ways |
| I am being rate limited, and backing off does not help | a-cached-429-is-not-a-rate-limit |
| A figure is correct and its premise is dead | a-number-that-moves-without-new-data-is-an-assumption |
| The file validates and the output still looks wrong | a-generated-document-is-unverified-until-you-render-it |
| My test harness reports bugs that do not reproduce by hand | an-instrument-that-reshapes-input-fabricates-the-test |
