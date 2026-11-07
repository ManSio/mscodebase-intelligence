# E54 — frozen hypotheses (before the first run)

**Idea:** no automatic router. The agent already knows whether it wants docs or
code; pass `intent="docs"` explicitly to `search_code` / engine. Test the upper
bound: explicit intent derived from gold (docs queries -> "docs", code -> "code")
on the clean index with intent-aware demotion.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | explicit-intent docs hit@1 >= 0.50 | < 0.50 | PASS |
| H2 | explicit-intent overall hit@1 >= 0.75 | < 0.75 | PASS |
| H3 | code hit@1 >= 0.825 (unchanged) | < 0.825 | PASS |
| H4 | overall hit@5 >= 0.85 | < 0.85 | PASS |
| H5 | p50 < 5,000 ms | >= 5,000 | PASS |
| H6 | explicit-intent hit@1 >= 0.95 | < 0.95 | **FAIL** |

Baseline clean: 0.688/0.750; code 0.825/0.900; docs 0/0.
