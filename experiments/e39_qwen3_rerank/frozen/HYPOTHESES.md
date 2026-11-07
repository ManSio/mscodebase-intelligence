# E39 pilot — frozen hypotheses (before the first run)

Pilot panel: 16 queries from E30 (every 3rd), frozen
`QUERIES_PILOT.jsonl` sha `3a8e6581…`. Corrected index, E33 demote ON, P3 off.

Reranker: **Qwen3-Reranker-0.6B-seq-cls ONNX** (1.19 GB, CPU), prompt format from
the model card, sigmoid score, top10.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | Qwen3 top10 improves hit@1 by >= 2 on pilot | delta < 2 | PASS |
| H2 | p50 < 5000 ms | p50 >= 5000 ms | PASS |
| H3 | Qwen3 beats BGE-base on pilot | hit@1 <= BGE-base pilot | PASS |
| H4 | hit@1 >= 0.75 on pilot | hit@1 < 0.75 | **FAIL** (unknown; 95% far) |
| H5 | hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |
| H6 | top20 > top10 | hit@1(top20) <= hit@1(top10) | **FAIL** (bigger pool adds noise) |

If H1/H2 pass, run the full 48-query panel; otherwise stop.
