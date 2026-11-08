# E45 — frozen hypotheses (before the first run)

**Idea:** the agent supplies a *structured plan*, not a flood of rewrites:
one primary query + exact `must_include` tokens + exact `symbols`. The server
executes one query and applies deterministic boosts; no multi-query RRF.

Panel: E30 48 queries, corrected index, demote ON, P3 off, no reranker.
Frozen plans: `PLANS.jsonl` sha `093003f4…` (primary, must_include, symbols).

Arms:
- baseline: current `search_code` (original query + expansion)
- plan_primary: primary query only (`expand=False`)
- plan_must: primary + `must_include` ×2
- plan_symbols: primary + exact `symbols` ×2
- plan_full: primary + both boosts

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | plan_primary improves hit@1 by >= 1 over baseline | delta < 1 | PASS |
| H2 | plan_must improves hit@1 by >= 1 over plan_primary | delta < 1 | PASS |
| H3 | plan_symbols improves hit@1 by >= 1 over plan_primary | delta < 1 | **FAIL** (few exact symbols extracted) |
| H4 | plan_full reaches hit@1 >= 0.75 | hit@1 < 0.75 | **FAIL** (95% far) |
| H5 | plan_full p50 < 150 ms | p50 >= 150 ms | PASS |
| H6 | plan_full reaches hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |

No graph stage; plans are deterministic and frozen before the run.
