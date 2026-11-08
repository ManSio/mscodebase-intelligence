# E49 — hybrid code + fixed docs reserve

**Setup:** code PageRank + BM25 seeds; docs BM25 always; reserve 15%/25% of
token budget for docs. No classifier.

## Results (all 48)

| Arm | 1k | 2k | 4k |
|---|---:|---:|---:|
| base | 0.271 | 0.458 | 0.562 |
| bm25_code | 0.271 | 0.458 | 0.562 |
| hybrid_code | 0.271 | 0.458 | 0.562 |
| reserve15 | 0.250 | 0.500 | 0.583 |
| reserve25 | 0.208 | 0.458 | 0.604 |
| docs2_code | 0.271 | 0.479 | 0.562 |
| oracle | 0.396 | 0.604 | 0.729 |

p50 = 245 ms.

## Subsets

Code (40): base 0.325/0.550/0.675; reserve15 0.250/0.525/0.600.
Docs (8): reserve15 0.250/0.375/0.500; reserve25 0.375/0.500/0.750;
oracle 0.750/0.875/1.000.

## Verdict

- Token budget is **zero-sum**: docs need most of 1k to reach 0.75; code needs
  most of 1k to reach 0.325.
- Reserving 15% for docs **lowers** overall 1k below base (0.250 vs 0.271).
- H1–H7, H9 FAIL; H8 PASS (245 ms).
- Oracle ceiling 0.396/0.604/0.729; 95% impossible.
