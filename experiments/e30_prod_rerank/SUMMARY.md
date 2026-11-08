# E30 — production-like on-demand rerank on real MSCodeBase queries

**Panel:** 48 real queries (33 frozen E28 + 15 fresh docstring-derived), frozen
`frozen/QUERIES.jsonl` sha256 `d4934cb7…`. One project, one CPU machine.
**Index:** SQLite/FTS5 16,158 chunks / 1,473 files; PropertyGraph 13,744 nodes /
45,455 edges. All runs use the same index and the same candidate pipeline.

## Main run

| Config | hit@1 | hit@5 | MRR | p50 ms | p95 ms | errors |
|---|---:|---:|---:|---:|---:|---:|
| no_rerank (clean control) | **0.625** | 0.729 | **0.662** | **109** | 187 | 0 |
| e5 384 top10 | 0.354 | 0.729 | 0.500 | 912 | 1223 | 0 |
| Q8 768 top10 | **0.604** | 0.729 | 0.653 | 4285 | 7556 | 0 |
| Q8 768 top20 | 0.604 | 0.729 | 0.653 | 3207 | 4840 | 0 |
| Q8 256 top10 | 0.583 | 0.729 | 0.646 | 2630 | 3026 | 0 |
| Q8 768 top10 cap800 | 0.562 | 0.729 | 0.620 | 1900 | 2412 | 0 |
| Q4 768 top10 | 0.562 | 0.729 | 0.632 | 1867 | 2396 | 0 |
| Q4 768 top20 | 0.562 | 0.729 | 0.632 | 1792 | 2187 | 0 |
| Q4 256 top10 | 0.562 | 0.729 | 0.635 | 1965 | 2245 | 0 |

## Repeat of key configs (`_r2`)

| Config | hit@1 | p50 ms | p95 ms |
|---|---:|---:|---:|
| e5 384 top10 | 0.354 | 1148 | 1456 |
| Q8 768 top10 | 0.604 | 5141 | 6518 |
| Q4 768 top10 | 0.562 | 3872 | 4723 |
| no_rerank (clean) | **0.625** | **109** | 187 |

Quality is stable across repeats; latency varies 1.5–2× (CPU/thermal/order).

## Hypothesis outcomes (frozen before run)

| # | Hypothesis | Result |
|---|---|---|
| H1 | Q4 768 within 1 query of Q8 768 hit@1 | **FAIL** — 0.562 vs 0.604 = 2/48 |
| H2 | Q8 MRL 256 within 2 queries of 768 | **PASS** — 0.583 vs 0.604 = 1/48 |
| H3 | Q4 top20 improves hit@5 by ≥1 query | **FAIL** — 0.729 vs 0.729 |
| H4 | Q8 768 top10 p50 < 600 ms | **FAIL (expected)** — 4285 ms |
| H5 | e5 ≥2× faster than Q8 | **PASS** — 912 vs 4285 ms |
| H6 | cap800 within 1 query of no-cap | **FAIL (expected)** — 0.562 vs 0.604 = 2/48 |
| H7 | no-rerank hit@1 ≤ Q8 | **FAIL** — 0.625 vs 0.604 (no-rerank 1 query better) |
| H8 | Q4 within 20% of e5 latency | **FAIL (expected)** — 1867 vs 912 ms |

## What this means

1. **On-demand rerank does not beat the fused retrieval on this panel.**
   `no_rerank` is both the fastest (109 ms) and the best hit@1 (0.625).
   The 1-query difference vs Q8 (0.604) is noise-sized, but there is **no
   evidence of quality gain** for a 40× latency cost.
2. **If a reranker is required, Q8 768 is the quality leader** (0.604), then
   Q8 256 (0.583), then Q4 768 (0.562). Q4 is ~2× faster than Q8 at
   ~2 queries lower hit@1.
3. **MRL 256 is a good compromise** for Q8: 0.583 at 2.6 s vs 0.604 at 4.3 s.
4. **cap800 loses 2 queries** (0.562 vs 0.604) and saves ~2.4 s; not free.
5. **top20 does not improve hit@5** on this panel; no reason to pay for it.
6. **e5 is fast but weak** (0.354); as a reranker it is not competitive.

## Recommendation

- Do **not** enable on-demand rerank by default on this evidence. Keep it behind
  `MSCODEBASE_ONDEMAND_RERANK` and use the fused retrieval path (`no_rerank`)
  unless a larger panel shows a real gain.
- If quality-first and latency is acceptable: `Q8 768 top10` (0.604, ~4–5 s).
- If latency-first: `no_rerank` (109 ms, 0.625) or `e5` (0.9–1.1 s, 0.354).
- Re-run on a fresh >100-query panel before making a product claim; this 48-query
  panel is directional, not a production SLA.

## Artifacts

- `frozen/QUERIES.jsonl`, `frozen/QUERIES_FRESH.jsonl`, `frozen/HYPOTHESES.md`,
  `frozen/MANIFEST.md`
- `results/<config>.json` (raw per-query rows), `results/<config>_r2.json`
- `run.log`, `run_r2.log`
