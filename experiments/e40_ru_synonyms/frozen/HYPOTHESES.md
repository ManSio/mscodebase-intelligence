# E40 — frozen hypotheses (before the first run)

Panel: E30 48 queries, sha `d4934cb7…`. Corrected index, E33 demote ON, P3 off,
no reranker. The panel is mostly Russian NL (E28 queries) + 15 fresh docstrings.

Arms:
- baseline: current English-only query expansion
- ru_synonyms: + `synonyms_ru.RU_EN` / `RU_PHRASES` variants (max 4 variants)

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | RU synonyms improve hit@1 by >= 2 | delta < 2 | PASS |
| H2 | RU synonyms improve hit@5 by >= 1 | delta < 1 | PASS |
| H3 | p50 stays < 120 ms | p50 >= 120 ms | PASS |
| H4 | RU synonyms reach hit@1 >= 0.75 | hit@1 < 0.75 | **FAIL** (95% far) |
| H5 | RU synonyms reach hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |
| H6 | RU synonyms do not reduce hit@1 (precision guard) | hit@1 lower than baseline | PASS |

Metrics: hit@1/hit@5/MRR, p50/p95. Variants are merged by RRF; no index change.
