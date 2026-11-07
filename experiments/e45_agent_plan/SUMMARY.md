# E45 — structured agent search plan (48 real queries)

**Plan:** one primary keyword query + exact `must_include` tokens + exact
`symbols`. The server executes one query and applies deterministic ×2 boosts;
no multi-query RRF. Frozen plans: `PLANS.jsonl` sha `093003f4…`.

| Arm | hit@1 | hit@5 | MRR | p50 |
|---|---:|---:|---:|---:|
| baseline (current) | 0.688 | 0.771 | 0.713 | 79 ms |
| plan_primary | 0.708 | 0.750 | 0.718 | 69 ms |
| **plan_must** | **0.708** | **0.771** | **0.722** | **71 ms** |
| plan_symbols | 0.708 | 0.750 | 0.718 | 72 ms |
| **plan_full** | **0.708** | **0.771** | **0.722** | **72 ms** |

## Hypothesis outcomes

| # | Hypothesis | Result |
|---|---|---|
| H1 | plan_primary +1 hit@1 | **PASS** — 0.688 → 0.708 |
| H2 | plan_must +1 hit@1 over primary | **FAIL** — h1 same; h5 recovers 0.750 → 0.771 |
| H3 | plan_symbols +1 hit@1 | **FAIL** — same 0.708 |
| H4 | plan_full >= 0.75 | **FAIL** — 0.708 |
| H5 | p50 < 150 ms | **PASS** — 72 ms |
| H6 | plan_full >= 0.95 | **FAIL** — 0.708 |

## What this means

1. **A structured agent plan is a real, small win:** +1 hit@1 (0.688 → 0.708),
   same hit@5 (0.771), faster (79 → 72 ms).
2. **One primary query beats a flood of rewrites** (E44 agent_all was neutral and
   slower); `must_include` recovers the hit@5 lost by keyword-only.
3. **Exact `symbols` add nothing here** — the extracted set is mostly empty or
   noisy; a real agent must supply the exact symbol.
4. 95% is still far; the agent-plan layer is worth shipping because it improves
   UX and latency, not because it closes the 95% gap.

## Recommendation

- Implement optional `primary_query`, `must_include`, `symbols`, `intent` in
  `search_code` (plan fields), and a `plan_search` tool that returns a suggested
  plan. The agent can override the plan.
- Keep deterministic boosts ×2 for `must_include`; do not fuse multiple queries.
- 95% hit@1 remains unrealistic on this mixed panel.
