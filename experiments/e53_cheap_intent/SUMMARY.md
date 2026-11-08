# E53 — cheap lexical intent-aware demotion

**No LLM router.** Extended `auto_detect_intent` with Russian docs/architecture
signals; tested with `_demote_intent_aware` on/off on the clean index.

| Arm | hit@1 | hit@5 | code h1/h5 | docs h1/h5 | p50 |
|---|---:|---:|---:|---:|---:|
| baseline | 0.688 | 0.750 | 0.825 / 0.900 | 0.000 / 0.000 | 88 ms |
| intent | 0.688 | 0.771 | 0.825 / 0.900 | 0.000 / 0.125 | 86 ms |

False-positive docs intent on code gold: **4** (`E28-29`, `E28-32`, `D01`, `D12`).

## Verdict

- Cheap intent recovers **one docs hit@5**, but **not docs hit@1**.
- Code quality unchanged; p50 unchanged.
- H1/H2/H6/H8 FAIL; H3/H4/H5/H7 PASS.
- Intent alone is insufficient: docs are not in the candidate pool. Need a
  separate docs-only FTS channel (one extra query, no LLM).
