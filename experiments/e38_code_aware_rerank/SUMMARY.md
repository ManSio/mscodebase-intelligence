# E38 — BGE-reranker-base ONNX int8 (code-aware rerank attempt)

**Panel:** E30 48 queries, corrected index (symbol_name populated), E33 demote ON,
P3 off, no stored vectors. Reranker: `onnx-community/bge-reranker-base-ONNX`
int8 (279 MB, XLM-R cross-encoder).

| Arm | hit@1 | hit@5 | MRR | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| **demote** | **0.688** | **0.771** | **0.713** | **84 ms** | 148 ms |
| bge_base_top10 | 0.625 | 0.708 | 0.658 | 3139 ms | 3580 ms |
| bge_base_top20 | 0.583 | 0.688 | 0.627 | 6028 ms | 6884 ms |

## Hypothesis outcomes

| # | Hypothesis | Result |
|---|---|---|
| H1 | BGE-base top10 +2 hit@1 | **FAIL** — 0.625 (worse) |
| H2 | BGE-base top10 +1 hit@5 | **FAIL** — 0.708 (worse) |
| H3 | top20 > top10 | **FAIL** — 0.583 vs 0.625; h5 worse |
| H4 | p50 < 2000 ms | **FAIL** — 3139 ms |
| H5 | hit@1 >= 0.75 | **FAIL** — 0.625 |
| H6 | hit@1 >= 0.95 | **FAIL** — 0.625 |
| H7 | beats MS MARCO MiniLM (0.417) | **PASS** — 0.625 |

## What this means

1. **BGE-reranker-base is also out-of-domain for code.** It lowers hit@1
   (0.688 → 0.625) and hit@5 (0.771 → 0.708) while costing 3–6 s.
2. **MS MARCO MiniLM (E35) and BGE-base (E38) both hurt.** The only reranker
   that came close was BGE-M3 (0.646 hit@1 on the old panel) but it was 6.6 s
   and still below the deterministic demote pipeline.
3. **Reranking is not the lever on this panel.** The fused retrieval + bucket
   weights + demote + O1 is already stronger than the available generic
   cross-encoders.
4. The only untested code-aware option is Qwen3-Reranker-0.6B, but the available
   ONNX is 1.2 GB and CPU inference is likely 1–3 s/query; a pilot is the only
   way to know.

## Recommendation

- Keep the deterministic pipeline: **0.688 hit@1 / 0.771 hit@5 / 84 ms**, with
  `MSCODEBASE_DEMOTE_NON_CODE=true`, `MSCODEBASE_P3_ANCHOR=false`.
- Do **not** ship a generic cross-encoder reranker.
- 95% hit@1 is not realistic on this panel with available models. If pursued,
  next is a Qwen3-Reranker-0.6B pilot, not another generic reranker.
