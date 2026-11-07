# E34b — stronger deterministic graph/PRF boosts

**Panel:** E30 48 queries, frozen `d4934cb7…`. Same index/graph. E33 demote ON.

| Arm | hit@1 | hit@5 | MRR | p50 ms |
|---|---:|---:|---:|---:|
| demote | 0.688 | 0.729 | 0.705 | 94 |
| graph_x15 | 0.688 | 0.729 | 0.705 | 93 |
| prf_x12 | 0.688 | 0.729 | 0.705 | 94 |
| both_x15 | 0.688 | 0.729 | 0.705 | 94 |

**Verdict:** all arms identical. Raising graph/PRF boosts to ×1.5/×1.2 still does
not change top-5: the added candidates either duplicate existing hits or are not
the gold file. Deterministic candidate expansion is exhausted on this panel.
H1/H2/H3/H4/H6 FAIL; H5 PASS (p50 <300 ms).

**Next:** a code-aware reranker (not MS MARCO MiniLM) or chunking/recall work.
