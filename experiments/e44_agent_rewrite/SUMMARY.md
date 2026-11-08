# E44 — agent-style query rewrites (48 real queries)

**Idea:** the agent provides several search formulations; the engine fuses them.
Frozen rewrites: `QUERIES_REWRITTEN.jsonl` sha `9f87fbb2…` (original, keywords,
identifiers, RU→EN, concepts). Corrected index, demote ON, P3 off, no reranker.

| Arm | hit@1 | hit@5 | MRR | p50 |
|---|---:|---:|---:|---:|
| baseline | 0.688 | 0.771 | 0.713 | 84 ms |
| **keywords** (stopword-stripped) | **0.708** | 0.771 | **0.723** | **78 ms** |
| identifiers only | 0.583 | 0.750 | 0.652 | 69 ms |
| agent_all (all rewrites) | 0.688 | 0.771 | 0.713 | 147 ms |

## What this means

1. **A single clean keyword query is slightly better than the baseline**
   (+1 hit@1, +0.010 MRR) and faster. Stripping question words helps.
2. **Identifier-only is worse** (0.583): naive identifier extraction is noisy;
   a real agent must pick the exact symbol, not all code-like tokens.
3. **Fusing all rewrites is neutral and slower** (0.688/0.771, 147 ms): the noisy
   variants dilute RRF, exactly the opposite of "more queries = better".
4. The agent-query idea is right, but the implementation must be **selective**:
   one primary query per intent, not a flood of variants.

## Proposed agent-facing API

`search_code` should accept a structured plan instead of relying on one string:

```json
{
  "primary_query": "rate limiter threading.Lock",
  "must_include": ["threading.Lock", "asyncio.Lock"],
  "concepts": ["rate_limit", "concurrency"],
  "symbols": ["RateLimiter"],
  "intent": "code",
  "layer": "core"
}
```

The engine executes the primary query and uses `must_include`/`symbols` as
filters or boosts; it does not fuse every possible rewrite. The agent (LLM) is
the planner; the server stays deterministic.

## Next

- Implement `primary_query` + `must_include` + `symbols`/`concepts` in
  `search_code` (new optional fields), and a `plan_search` tool that returns a
  suggested plan.
- Evaluate with agent-selected plans on the same panel; target +2–4 hit@1,
  not 95%.
