# E50 — frozen hypotheses (before the first run)

**Idea:** E48/E49 showed token budget is zero-sum: docs need most of 1k to hit
75%, code needs most of 1k to hit 32.5%. Routing is the real problem. Replace
keyword hints with a **BM25 score-margin router**: route docs when the best doc
relevance exceeds `threshold * best code relevance`.

Panel: E30 48 queries. No embeddings/LLM. Thresholds evaluated: 0.8, 1.0, 1.2,
1.5, 2.0. Held-out check: pick the best threshold on odd IDs, evaluate on even.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | best score-route 1k >= base + 5 p.p. (base 0.271) | < +5 | PASS |
| H2 | best score-route 1k >= oracle - 5 p.p. | < oracle-5 | PASS |
| H3 | best score-route 1k >= 40% | < 40% | **FAIL** |
| H4 | best score-route 2k >= 60% | < 60% | PASS |
| H5 | score router catches >= 6 of 8 docs queries | < 6 | PASS |
| H6 | held-out (even IDs) keeps >= 90% of full-panel 1k | < 90% | PASS |
| H7 | 4k >= 95% | < 95% | **FAIL** |
| H8 | p50 < 5,000 ms | >= 5,000 | PASS |

References: E48 oracle 0.396/0.625/0.729; E49 reserve15 0.250/0.500/0.583.
