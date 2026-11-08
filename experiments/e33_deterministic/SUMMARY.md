# E33 — deterministic ranking signals on 48 real queries

**Panel:** E30 48 queries, frozen `d4934cb7…`. Same SQLite/FTS5 index and graph.
No embeddings, no reranker. Pool = top-30 fused, then deterministic post-ranking.

## Results

| Arm | hit@1 | hit@5 | MRR | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| baseline | 0.625 | 0.708 | 0.657 | 155 | 332 |
| fts_weights | 0.625 | 0.708 | 0.657 | 103 | 166 |
| **fts_weights_demote** | **0.688** | **0.729** | **0.705** | **97** | 164 |
| fts_weights_demote_prior | 0.667 | 0.708 | 0.681 | 98 | 148 |

## Hypothesis outcomes

| # | Hypothesis | Result |
|---|---|---|
| H1 | FTS5 field weights +2 hit@1 | **FAIL** — 0.625 unchanged |
| H2 | test/doc demotion +1 hit@1 | **PASS** — 0.688 (+3 queries) |
| H3 | caller prior + exact-name +1 over demote | **FAIL** — 0.667 vs 0.688 (worse) |
| H4 | all deterministic >= 0.70 hit@1 | **FAIL** — 0.688 |
| H5 | p50 < 300 ms | **PASS** — 97–155 ms |
| H6 | deterministic reaches 0.95 hit@1 | **FAIL** — 0.688 |

## What this means

1. **Test/doc/experiment/fixture demotion is a real deterministic win:**
   hit@1 0.625 → **0.688** (+3 queries), hit@5 0.729, p50 **97 ms**.
2. **FTS5 field weights alone are neutral** (same quality, slightly faster).
3. **Caller prior + exact-name/path boost hurts** on this panel (0.667 vs 0.688):
   the prior promotes noisy callers; exact-name is already handled by O1.
4. 95% is still far; deterministic signals alone won't reach it.

## Recommendation

- Add **test/doc/experiment/fixture demotion** to production behind a config flag
  (e.g. `MSCODEBASE_DEMOTE_NON_CODE=true`). It is cheap and improves hit@1.
- Implemented: `SearchConfig.demote_non_code` + demotion in
  `Searcher.hybrid_search_async` before the final cut. Enabled in `.env` and
  ext `.env` as `MSCODEBASE_DEMOTE_NON_CODE=true`.
- Keep FTS5 field weights optional (no quality gain, small speed gain).
- Do **not** add caller prior as-is.
- Next: combine demotion with graph expansion and a small cross-encoder; then
  measure the combined stack. 95% hit@5 remains the realistic target.

## Artifacts

- `frozen/QUERIES.jsonl`, `frozen/HYPOTHESES.md`, `frozen/MANIFEST.md`
- `results/baseline.json`, `results/fts_weights.json`,
  `results/fts_weights_demote.json`, `results/fts_weights_demote_prior.json`
- `run.log`
