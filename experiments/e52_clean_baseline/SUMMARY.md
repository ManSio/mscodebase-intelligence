# E52 — clean-index baseline audit

**Clean index:** removed 9,089 of 16,347 chunks (`experiments/**` +
`.mscodebase/**`), kept 7,258. Leakage file absent from clean top-100 (0/48).

## Results (48 queries)

| Index | Arm | hit@1 | hit@5 | p50 |
|---|---|---:|---:|---:|
| contaminated | BM25 | 0.458 | 0.750 | 185 ms |
| contaminated | production | 0.688 | 0.771 | 144 ms |
| clean | BM25 | 0.542 | 0.771 | 140 ms |
| clean | production | 0.688 | 0.750 | 72 ms |

Leakage hits in BM25 top-100: **19/48** contaminated, **0/48** clean.

## Subsets (clean)

- BM25: code 0.625/0.875; docs 0.125/0.250.
- Production: **code 0.825/0.900; docs 0.000/0.000.**

## Verdict

- **Production hit@1 is not inflated**: 0.688 contaminated = 0.688 clean.
- **Hit@5 was slightly inflated**: 0.771 → **0.750** (one leaked docs query).
- **BM25 was materially hurt by leakage**: 0.458 → 0.542 hit@1.
- **Production is excellent on code (0.825/0.900) and zero on docs (0/0).**
- H1 FAIL (0.542 < 0.55); H2–H9 PASS; H10 FAIL (docs 0 < 0.125).

## Corrected baseline

`0.688 hit@1 / 0.750 hit@5` (not 0.771). Supersedes the hit@5 in E30/E45.

## Oracle ceiling with a perfect router

- code production hit@1 0.825 (40 queries)
- docs-only BM25 hit@1 0.750 (8 queries)
- overall: **(40×0.825 + 8×0.750)/48 = 0.8125 hit@1**, hit@5 ≈ 0.9167.

So a **semantic router + docs-only BM25** can raise hit@1 from 0.688 to ~0.81;
95% still needs a stronger code channel or an LLM agent.
