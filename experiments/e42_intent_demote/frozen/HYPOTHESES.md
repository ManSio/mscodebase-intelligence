# E42 — frozen hypotheses (before the first run)

**Trigger:** E41 diagnostic showed 13/48 gold not in RRF top5; 5 of them are docs
queries whose gold is `docs/...`, and the unconditional E33 demote (docs ×0.3)
pushes them out. Fix: for docs-intent queries, do not demote `docs/`.

Panel: E30 48 queries, corrected index, P3 off, no reranker. Arms:
- baseline: demote all non-code (docs/tests/experiments/fixtures)
- intent_aware: docs-intent queries keep docs; code-intent demotes all

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | intent-aware improves hit@1 by >= 2 | delta < 2 | PASS |
| H2 | intent-aware improves hit@5 by >= 2 | delta < 2 | PASS |
| H3 | code queries do not lose hit@1 | code hit@1 lower | PASS |
| H4 | hit@1 >= 0.75 | hit@1 < 0.75 | **FAIL** (95% far) |
| H5 | hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |

Metrics: hit@1/hit@5/MRR, p50/p95; split by docs/code subset.
