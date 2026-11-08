# E46b — frozen hypotheses (before the first run)

**Idea:** E46 personalized PageRank used raw Russian query tokens, which rarely
match English symbol/file names. Map RU→EN via `synonyms_ru.RU_EN` before
biasing PageRank. Same complete graph (9,315 nodes / 47,286 edges / 759 files).

Panel: E30 48 queries. Budgets 1k/2k/4k tokens. No embeddings, no LLM.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | RU→EN bias improves 1k coverage by >= 10 p.p. over E46 personalized | delta < 10 | PASS |
| H2 | RU→EN 2k coverage >= 60% | < 60% | PASS |
| H3 | RU→EN 4k coverage >= 75% | < 75% | **FAIL** (docs gold not in graph) |
| H4 | RU→EN 4k coverage >= 95% | < 95% | **FAIL** |
| H5 | p50 < 300 ms | >= 300 ms | PASS |

E46 personalized baseline: 27.1% / 41.7% / 52.1% at 1k/2k/4k (all 48).
Code-only baseline: 32.5% / 50.0% / 62.5%.
