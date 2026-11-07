# E47 — PageRank + docs nodes + BM25 seed

**Setup:** 759 code files + 348 docs = 1,107 files; docs linked to code by
symbol mentions; RU→EN expansion; BM25 top-20 seed. No embeddings/LLM.

## Results (all 48)

| Arm | 1k | 2k | 4k |
|---|---:|---:|---:|
| bm25 | 0.062 | 0.062 | 0.062 |
| base (code-only PageRank) | 0.271 | 0.458 | 0.562 |
| docs | 0.042 | 0.188 | 0.458 |
| docs_bm25 | 0.042 | 0.229 | 0.479 |

p50 = 1,113 ms.

## Subsets

Code (40): base 0.325/0.550/0.675; docs 0.050/0.225/0.475;
docs_bm25 0.050/0.200/0.475.
Docs (8): base 0/0/0; docs 0/0/0.375; docs_bm25 0/0.375/0.500;
bm25 0.375/0.375/0.375.

## Verdict

- **Naive docs nodes dilute the code graph**: code-only 1k drops 32.5% → 5%.
- **BM25 seed does not merge the channels**: it lifts docs, pushes code down.
- **BM25 is good for docs only** (37.5% at 1k, 0% code).
- **p50 1.1 s** — three PageRanks per query is too slow.
- H1–H7 all FAIL (H7 as expected: BM25 overall < PageRank overall).

## Lesson

Do not put docs into the same PageRank graph. Use **two channels**:
1. code PageRank (as E46b);
2. docs BM25;
then merge by budget/query type outside PageRank. One PageRank per query,
not three.
