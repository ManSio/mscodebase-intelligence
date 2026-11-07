# E46 — frozen hypotheses (before the first run)

**Idea (Aider-style):** build a file-level graph from PropertyGraph references
(CALLS/ASSIGNED_FROM/IMPORTS/DECORATES/OVERRIDES), run personalized PageRank
with query tokens as the restart bias, render the top symbols within a token
budget, and check whether the gold file is in the map.

Panel: E30 48 queries. Graph: backup `graph.db` with 13,744 nodes
(CALLS 30,532; ASSIGNED_FROM 7,605; IMPORTS 2,941; DECORATES 317; OVERRIDES 8).
No embeddings, no LLM.

Arms:
- degree: files sorted by in-degree (simple baseline)
- global: PageRank uniform (no query bias)
- personalized: PageRank biased to query tokens
- budgets: 1k / 2k / 4k tokens

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | personalized 1k includes gold file in >= 60% queries | < 60% | PASS |
| H2 | personalized beats global by >= 10 p.p. at 1k | delta < 10 | PASS |
| H3 | personalized 2k includes gold in >= 80% | < 80% | PASS |
| H4 | personalized 4k includes gold in >= 95% | < 95% | **FAIL** (hard queries/docs) |
| H5 | map build p50 < 500 ms | >= 500 ms | PASS |
| H6 | PageRank beats degree baseline by >= 10 p.p. at 1k | delta < 10 | **FAIL** (degree may be enough) |

Metrics: gold-file coverage at 1k/2k/4k, map tokens, p50/p95 build time.
