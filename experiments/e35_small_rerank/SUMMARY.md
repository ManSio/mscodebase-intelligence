# E35 — small ONNX cross-encoder (ms-marco-MiniLM-L-6-v2 int8)

**Panel:** E30 48 queries, frozen `d4934cb7…`. Same index/graph. E33 demote ON.
No stored vectors: the model scores (query, passage) pairs live.

| Arm | hit@1 | hit@5 | MRR | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| **demote** | **0.688** | **0.729** | **0.705** | **85** | 140 |
| minilm_top10 | 0.417 | 0.646 | 0.513 | 723 | 771 |
| minilm_top20 | 0.417 | 0.542 | 0.469 | 1405 | 1500 |

## Hypothesis outcomes

| # | Hypothesis | Result |
|---|---|---|
| H1 | MiniLM +2 hit@1 | **FAIL** — 0.417 (much worse) |
| H2 | MiniLM +1 hit@5 | **FAIL** — 0.646 (worse) |
| H3 | top20 > top10 | **FAIL** — 0.417 vs 0.417; h5 worse |
| H4 | p50 < 1000 ms | **PASS** — 723 ms top10 |
| H5 | hit@1 >= 0.75 | **FAIL** — 0.417 |
| H6 | hit@1 >= 0.95 | **FAIL** — 0.417 |
| H7 | beats BGE-M3 top10 (0.646) | **FAIL** — 0.417 |

## What this means

1. **MS MARCO MiniLM is out-of-domain for code.** It reorders code passages by
   web-passage relevance and destroys the fused ranking (0.688 → 0.417).
2. **Speed is fine** (723 ms for top10), but quality is not; this model is not a
   candidate for production.
3. The external research warned that small cross-encoders need a **code-aware**
   or domain-matched model; this run confirms it.
4. Best quality remains **E33 demote: 0.688 hit@1 / 0.729 hit@5 / 85–119 ms**.

## Recommendation

- Do not use MS MARCO MiniLM for code reranking.
- Next reranker should be **code-aware**: Qwen3-Reranker-0.6B (MTEB-Code 73.4)
  or a code-tuned cross-encoder; benchmark CPU latency before adopting.
- In parallel, the 95% hit@5 target needs **recall**: chunking 32–64 lines /
  AST-aware, query expansion, or semantic anchors. Reranking alone will not
  close the gap.

## Artifacts

- `frozen/QUERIES.jsonl`, `frozen/HYPOTHESES.md`, `frozen/MANIFEST.md`
- `results/demote.json`, `results/minilm_top10.json`, `results/minilm_top20.json`
- `run.log`
