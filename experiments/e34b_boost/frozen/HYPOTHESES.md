# E34b — frozen hypotheses (before the first run)

Panel: E30 48 queries, sha `d4934cb7…`. Same index/graph. All arms deterministic,
E33 demote ON. E34 showed 0.6× graph / 0.8× PRF candidates never enter top-5;
E34b raises the boosts.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | graph ×1.5 improves hit@1 by >= 2 over demote | delta < 2 | PASS |
| H2 | PRF ×1.2 improves hit@5 by >= 1 | delta < 1 | PASS |
| H3 | graph+PRF × boosts improves hit@1 by >= 3 | delta < 3 | PASS |
| H4 | best arm reaches hit@1 >= 0.75 | hit@1 < 0.75 | **FAIL** |
| H5 | p50 < 300 ms | p50 >= 300 ms | PASS |
| H6 | best arm reaches hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |

Arms: demote, graph_x15, prf_x12, both_x15.
