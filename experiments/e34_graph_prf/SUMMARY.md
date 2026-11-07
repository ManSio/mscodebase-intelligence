# E34 — deterministic graph expansion + PRF (48 real queries)

**Panel:** E30 48 queries, frozen `d4934cb7…`. Same SQLite/FTS5 index and graph.
No embeddings, no reranker. E33 demote non-code is ON for every arm.

## Results

| Arm | hit@1 | hit@5 | MRR | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| demote (E33 winner) | 0.688 | 0.729 | 0.705 | 119 | 177 |
| demote_prf | 0.688 | 0.729 | 0.705 | 108 | 173 |
| demote_graph | 0.688 | 0.729 | 0.705 | 108 | 168 |
| demote_graph_prf | 0.688 | 0.729 | 0.705 | 114 | 184 |

## Hypothesis outcomes

| # | Hypothesis | Result |
|---|---|---|
| H1 | PRF +2 hit@1 | **FAIL** — 0.688 unchanged |
| H2 | graph +2 hit@5 | **FAIL** — 0.729 unchanged |
| H3 | graph+PRF +3 hit@1 | **FAIL** — 0.688 unchanged |
| H4 | graph+PRF >= 0.75 hit@1 | **FAIL** — 0.688 |
| H5 | p50 < 300 ms | **PASS** — 108–119 ms |
| H6 | graph+PRF >= 0.95 hit@1 | **FAIL** — 0.688 |
| H7 | graph alone +1 hit@1 | **FAIL** — 0.688 unchanged |

## What this means

1. **PRF and graph expansion added candidates, but none entered the top-5.**
   The added candidates scored below the existing fused top-5 (PRF 0.8×,
   graph 0.6× of top-1), so the output was identical.
2. **This is a clean negative result:** deterministic candidate expansion alone
   does not move the top-5 on this panel. The bottleneck is the ranker, not the
   candidate pool (at least for these 48 queries).
3. E33 demote remains the only deterministic win so far: hit@1 0.688, p50 97 ms.

## Recommendation

- Do not add PRF/graph expansion to production as-is.
- If graph expansion is to help, it needs a **stronger deterministic boost**
  (e.g. ×1.5) or a ranker that knows when a caller/callee is the answer — test
  as a separate arm before shipping.
- Next: **E35 — small fast cross-encoder** (bge-reranker-base / MiniLM) over
  top-10. Deterministic levers are nearly exhausted at the candidate level;
  precision needs a ranker.
- 95% hit@1 remains unrealistic; 95% hit@5 is the target.

## Artifacts

- `frozen/QUERIES.jsonl`, `frozen/HYPOTHESES.md`, `frozen/MANIFEST.md`
- `results/demote.json`, `results/demote_prf.json`,
  `results/demote_graph.json`, `results/demote_graph_prf.json`
- `run.log`
