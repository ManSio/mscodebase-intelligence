# E31 — BGE-M3 cross-encoder rerank over fused lexical/graph candidates

**Panel:** same 48 real MSCodeBase queries as E30 (33 E28 + 15 fresh), frozen
`d4934cb7…`. Same SQLite/FTS5 index (16,158 chunks) and PropertyGraph.
**No vectors stored.** Candidate pool from SQLite FTS5 + BM25 + graph; BGE-M3
reranks the top-N.

## Results

| Config | hit@1 | hit@5 | MRR | p50 ms | p95 ms | errors |
|---|---:|---:|---:|---:|---:|---:|
| **no_rerank** (fused top5) | 0.625 | 0.729 | 0.662 | **107** | 181 | 0 |
| **BGE top10** | **0.646** | 0.771 | **0.698** | 6577 | 12641 | 0 |
| BGE top30 | 0.562 | **0.812** | 0.662 | 19521 | 25484 | 1 |
| BGE top50 | — | — | — | — | — | **timeout** (30 min) |

## Hypothesis outcomes

| # | Hypothesis | Result |
|---|---|---|
| H1 | BGE top30 hit@1 +2 queries over no-rerank | **FAIL** — 0.562 vs 0.625 (worse) |
| H2 | BGE top30 hit@5 +1 query | **PASS** — 0.812 vs 0.729 (+4 queries) |
| H3 | BGE top30 p50 < 2000 ms | **FAIL** — 19521 ms |
| H4 | BGE top50 improves hit@1 over top30 | **⏳ not run** — timed out |
| H5 | BGE reaches hit@1 >= 0.95 | **PASS** (expected fail) — max 0.646 |
| H6 | BGE beats cosine embeddinggemma-2 Q8 (0.604) | **PASS** — 0.646 top10 |
| H7 | BGE top10 equals top30 hit@1 | **FAIL (expected)** — 0.646 vs 0.562 |

## What this means

1. **BGE top10 is the best hit@1 so far** (0.646, +1 query over no-rerank), and
   hit@5 0.771 (+2 queries). But p50 **6.6 s** — 60× slower than no-rerank.
2. **BGE top30 raises hit@5 to 0.812** (+4 queries) but **lowers hit@1 to 0.562**
   and takes **19.5 s** — not production-viable.
3. **95% is not reached.** Best hit@1 0.646, best hit@5 0.812. The 95% target is
   not realistic on this panel with BGE-M3 alone.
4. **BGE-M3 (568M Q4) is too heavy on this CPU** for interactive use. External
   evidence points to small ONNX cross-encoders (e.g. `bge-reranker-base`,
   `ms-marco-MiniLM-L-12-v2`) at ~30–60 ms/100 candidates — next experiment.
5. **Bigger pool ≠ better hit@1.** Top30 improves recall (hit@5) but adds noise
   that the reranker promotes; top10 is the safer pool.

## Recommendation

- Do **not** ship BGE-M3 rerank as default: 6.6–19.5 s p50.
- Next: test a **small fast cross-encoder** (bge-reranker-base / MiniLM-L6) on the
  same panel; target p50 < 1 s with hit@1 ≥ 0.65.
- In parallel, improve first-stage recall (code-aware BM25, exact-name field,
  graph expansion, query expansion) — the 95% hit@5 target needs recall, not only
  reranking.
- Keep `MSCODEBASE_ONDEMAND_RERANK=false` (E30) and BGE rerank behind a flag.

## Artifacts

- `frozen/QUERIES.jsonl`, `frozen/HYPOTHESES.md`, `frozen/MANIFEST.md`
- `results/no_rerank.json`, `results/bge_top10.json`, `results/bge_top30.json`
- `run.log` (empty: the process was killed by the 30-min harness timeout on top50)
