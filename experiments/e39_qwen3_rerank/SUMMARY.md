# E39 pilot — Qwen3-Reranker-0.6B-seq-cls ONNX (rejected)

**Pilot panel:** 16 queries from E30 (every 3rd), frozen
`QUERIES_PILOT.jsonl` sha `3a8e6581…`. Corrected index, E33 demote ON, P3 off.
Reranker: Qwen3-Reranker-0.6B-seq-cls ONNX (1.19 GB, fp16, CPU), model-card
prompt format, sigmoid score.

| Arm | hit@1 | hit@5 | MRR | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| **demote** | **0.625** | **0.688** | **0.646** | **116 ms** | 180 ms |
| qwen3_top10 | 0.500 | 0.562 | 0.512 | **28 941 ms** | 39 068 ms |
| qwen3_top20 | 0.438 | 0.562 | 0.490 | **54 788 ms** | 87 077 ms |

## Hypothesis outcomes

| # | Hypothesis | Result |
|---|---|---|
| H1 | Qwen3 +2 hit@1 on pilot | **FAIL** — 0.500 (worse) |
| H2 | p50 < 5000 ms | **FAIL** — 28.9 s |
| H3 | Qwen3 beats BGE-base | **FAIL** — 0.500 vs 0.625 |
| H4 | hit@1 >= 0.75 | **FAIL** — 0.500 |
| H5 | hit@1 >= 0.95 | **FAIL** — 0.500 |
| H6 | top20 > top10 | **FAIL** — 0.438 vs 0.500 |

## What this means

1. **Qwen3-Reranker-0.6B is not usable on this CPU.** 29 s for top10 and 55 s for
   top20 make it non-interactive; the fp16 ONNX model is too heavy.
2. **Quality also drops** (0.625 → 0.500 h1; 0.688 → 0.562 h5). The generic
   reranker does not understand our code chunks better than the fused ranking.
3. **Every tested reranker failed:** MS MARCO MiniLM (0.417), BGE-base (0.625),
   BGE-M3 (0.646), Qwen3 (0.500) — all below the deterministic demote pipeline.
4. **Reranking is not the lever on this panel.** The deterministic pipeline is
   already stronger than available generic cross-encoders.

## Final recommendation

- Ship the deterministic pipeline: **0.688 hit@1 / 0.771 hit@5 / 84 ms**,
  demote ON, P3 off.
- Do **not** ship a reranker.
- 95% hit@1 is not achievable on this 48-query mixed panel with the available
  CPU models. Further gains need a different architecture (code-specific dense
  index) or a much better model/hardware — not another generic reranker.
