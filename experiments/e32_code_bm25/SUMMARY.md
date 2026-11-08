# E32 — code-aware BM25 on 48 real queries

**Panel:** E30 48 queries, frozen `d4934cb7…`. Same SQLite/FTS5 index
(16,158 chunks) and PropertyGraph. Only the BM25 arm changes; no embeddings,
no reranker.

## Results

| Arm | hit@1 | hit@5 | MRR | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| **baseline** (current BM25) | **0.625** | 0.729 | **0.662** | 90 | 142 |
| code_b75 (split + boosts, b=0.75, no stop) | 0.562 | 0.708 | 0.620 | 98 | 134 |
| code_b45 (split + boosts, b=0.45, no stop) | 0.604 | 0.729 | 0.651 | 100 | 147 |
| **code_b45_stop** (split + boosts + stopwords) | 0.604 | **0.750** | 0.655 | 90 | 124 |

## Hypothesis outcomes

| # | Hypothesis | Result |
|---|---|---|
| H1 | code BM25 hit@1 +2 queries over baseline | **FAIL** — best 0.604 (-1 query) |
| H2 | b=0.45 hit@5 > b=0.75 | **PASS** — 0.729 vs 0.708 |
| H3 | stopwords improve hit@1 | **FAIL** — 0.604 vs 0.604 (h5 +1) |
| H4 | code BM25 p50 within 2× baseline | **PASS** — 90–100 ms vs 90 ms |
| H5 | code BM25 hit@1 >= 0.95 | **FAIL** — max 0.625 |

## What this means

1. **Identifier splitting + field boosts did not improve hit@1.** The baseline
   BM25 + FTS5 + graph fusion already handles exact identifiers well; the
   changed BM25 arm does not add a new signal.
2. **Stopwords + b=0.45 give +1 hit@5** (0.750 vs 0.729) at the same latency;
   that is directional, not a breakthrough.
3. **Best hit@1 remains the baseline** (0.625). 95% is far away on this panel.
4. The bottleneck is not tokenization — it is **recall/ranking**: pool
   construction, graph expansion, query expansion, and the reranker.

## Recommendation

- Keep `MSCODEBASE_CODE_BM25=false` by default (no hit@1 gain; stopword arm is
  a small h5 win only).
- Next experiments, in order:
  1. **Graph expansion** (callers/callees/imports) to increase recall.
  2. **Query expansion / pseudo-relevance feedback** (identifier + scope of the
     top hit) for short/NL queries.
  3. **Small fast cross-encoder** (not BGE-M3 568M) to rerank top-10 within ~1 s.
  4. **Semantic anchor index** (symbols/signatures/docstrings only) for NL
     queries — the only "semantic without full index" candidate with real
     upside.
- 95% hit@1 is not realistic on this mixed panel; 95% hit@5 is the target.

## Artifacts

- `frozen/QUERIES.jsonl`, `frozen/HYPOTHESES.md`, `frozen/MANIFEST.md`
- `results/baseline.json`, `results/code_b75.json`, `results/code_b45.json`,
  `results/code_b45_stop.json`
- `run.log`
