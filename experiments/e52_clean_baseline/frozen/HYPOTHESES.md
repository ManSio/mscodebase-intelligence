# E52 — frozen hypotheses (before the first run)

**Question:** how much did the indexed frozen panel inflate BM25 and production
baselines? Build a clean chunks DB excluding `experiments/**` and `.mscodebase/**`,
then compare BM25 and `Searcher.hybrid_search_async` on the same 48 queries.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | clean BM25 hit@1 >= 0.55 | < 0.55 | PASS |
| H2 | contaminated BM25 hit@1 < 0.50 (E51 = 0.458) | >= 0.50 | PASS |
| H3 | clean production hit@1 >= 0.60 | < 0.60 | PASS |
| H4 | contaminated production hit@1 >= clean production | < | FAIL? |
| H5 | clean production hit@5 >= 0.75 | < 0.75 | PASS |
| H6 | clean BM25 hit@5 >= 0.75 | < 0.75 | PASS |
| H7 | leakage file absent from clean top-100 for all queries | present | PASS |
| H8 | clean DB removes > 0 chunks | 0 | PASS |
| H9 | p50 < 5,000 ms | >= 5,000 | PASS |
| H10 | clean docs hit@1 >= 0.125 | < 0.125 | PASS |

Reference: E51 contaminated single 0.458/0.750; E51b filtered 0.562/0.771;
production deterministic 0.688/0.771 (possibly contaminated).
