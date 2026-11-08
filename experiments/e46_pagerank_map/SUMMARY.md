# E46 / E46b — Aider-style PageRank context map

**Graph:** complete PropertyGraph built from source (9,315 nodes / 47,286 edges /
759 code files; docs are not in the graph). No embeddings, no LLM.

**Method:** file graph from CALLS/ASSIGNED_FROM/IMPORTS/DECORATES/OVERRIDES;
personalized PageRank (damping 0.85, 30 iters) biased to query tokens; render
top symbols within 1k/2k/4k token budgets; check whether the gold file is in
the map.

## E46 — raw Russian tokens

| Arm | 1k | 2k | 4k |
|---|---:|---:|---:|
| degree (in-degree) | 0.000 | 0.021 | 0.146 |
| global PageRank | 0.021 | 0.042 | 0.104 |
| **personalized** | **0.271** | **0.417** | **0.521** |
| personalized, code-only (40 q) | 0.325 | 0.500 | 0.625 |
| personalized, docs (8 q) | 0.000 | 0.000 | 0.000 |

p50 = 207 ms.

## E46b — RU→EN expansion before PageRank

| Arm | 1k | 2k | 4k |
|---|---:|---:|---:|
| personalized | 0.271 | 0.458 | 0.562 |
| personalized, code-only | 0.325 | 0.550 | 0.675 |
| personalized, docs | 0.000 | 0.000 | 0.000 |

p50 = 204 ms.

## Verdict

- **Personalized PageRank dramatically beats degree/global** at every budget
  (code-only 32.5% vs 0% at 1k). The Aider mechanism is real.
- **RU→EN mapping helps at 2k/4k** (+5 p.p. code-only), not at 1k.
- **Coverage is far below the 95% target.** At 4k, code-only 67.5%; docs 0%.
- **Docs gold cannot appear**: the graph contains only code symbols, not docs.
- H1 (1k ≥60%) FAIL; H2 (beats global) PASS; H3 (2k ≥80%) FAIL; H4 (4k ≥95%)
  FAIL; H5 (p50 <500ms) PASS; H6 (beats degree) PASS.

## What this means

PageRank is a **context-selection** tool (repo map), not a replacement for
search. It is worth shipping as an auxiliary MCP tool (`repo_map`) with a token
budget, but to reach high coverage it needs:
1. docs/README nodes in the graph (or a separate doc graph);
2. better query personalization (RU→EN + exact symbols);
3. maybe combine with BM25 top files before PageRank.

95% coverage at 1k tokens is not realistic on this mixed panel.
