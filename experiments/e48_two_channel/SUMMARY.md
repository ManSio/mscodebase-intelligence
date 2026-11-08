# E48 — two-channel repo map: code PageRank + docs BM25

**Setup:** 759 code files / 348 docs; one code PageRank + one docs BM25 per
query; merge outside PageRank. No embeddings/LLM.

## Results (all 48)

| Arm | 1k | 2k | 4k |
|---|---:|---:|---:|
| base (code only) | 0.271 | 0.458 | 0.562 |
| bm25_docs | 0.125 | 0.167 | 0.167 |
| route | 0.292 | 0.458 | 0.562 |
| interleave | 0.208 | 0.438 | 0.625 |
| split75 | 0.208 | 0.438 | 0.604 |
| split50 | 0.146 | 0.396 | 0.625 |
| **oracle** (perfect routing) | **0.396** | **0.625** | **0.729** |

p50 = 323 ms.

## Subsets

Code (40): base 0.325/0.550/0.675; route 0.325/0.525/0.650;
interleave 0.175/0.450/0.600; oracle 0.325/0.550/0.675.
Docs (8): base 0/0/0; **bm25_docs 0.75/1.00/1.00**; route 0.125/0.125/0.125;
interleave 0.375/0.375/0.750; split50 0.375/0.750/1.00; oracle 0.75/1.00/1.00.

## Verdict

- **Docs BM25 is strong** (75% / 100% / 100%) when the docs channel is used.
- **Routing is the bottleneck**: keyword hints catch only 2 of 8 docs queries;
  route 1k = 29.2%.
- **Oracle ceiling at 1k = 39.6%**, just below 40%; 2k = 62.5%, 4k = 72.9%.
- **95% is impossible** with these two channels.
- H1/H2/H3/H4/H5/H7/H8 FAIL; H6 PASS (323 ms).

## Lesson

Docs must be a separate BM25 channel, but keyword routing is too brittle.
Next: always query docs BM25 (no classifier), append top docs to the code map
under a small token reserve; and improve the code channel at 1k (BM25 top-files
+ PageRank hybrid). Accept ~40% at 1k / ~62% at 2k as the realistic ceiling.
