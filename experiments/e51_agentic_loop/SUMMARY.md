# E51 / E51b — agentic retrieval loop + panel leakage

## E51 (contaminated)

`single_top1` for most queries was `experiments/4A_unit_of_return/frozen/f5/queries.md`
— a frozen panel file indexed in `chunks.db` that contains the same probes.
BM25 therefore returned the panel itself as top-1. E51 numbers are invalid for
quality comparison.

## E51b (filtered `experiments/**`)

| Arm | hit@1 | hit@5 |
|---|---:|---:|
| single BM25 | 0.562 | 0.771 |
| agent (2 calls) | 0.438 | 0.792 |

p50 = 140 ms; avg calls = 2.0; avg tokens = 1,048.
Code (40): single 0.650/0.875; agent 0.525/0.875.
Docs (8): single 0.125/0.250; agent 0.000/0.375.

## Verdict

- Deterministic expansion + graph neighbours **hurts hit@1** (0.438 vs 0.562)
  and only marginally improves hit@5 (+2.1 p.p.).
- H1/H2/H3/H5/H8/H9/H10 FAIL; H4/H6/H7/H11 PASS.
- The real blocker is **index hygiene**: frozen panels must not be indexed or
  must be excluded from retrieval/evaluation.
- A deterministic loop is not a real agent. 95% needs an LLM planner that
  chooses tools/queries and stops on evidence.
