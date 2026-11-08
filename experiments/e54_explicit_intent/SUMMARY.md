# E54 — explicit agent-supplied intent (upper bound)

Agent passes `intent_hint="docs"` for docs-gold and `"code"` for code-gold
(gold-derived; no router). Clean index, intent-aware demotion.

| Arm | hit@1 | hit@5 | code h1/h5 | docs h1/h5 | p50 |
|---|---:|---:|---:|---:|---:|
| baseline | 0.688 | 0.750 | 0.825 / 0.900 | 0.000 / 0.000 | 83 ms |
| explicit | 0.688 | 0.771 | 0.825 / 0.900 | 0.000 / 0.125 | 79 ms |

## Verdict

Even with **perfect explicit intent**, docs hit@1 stays 0. The engine's candidate
pool does not contain the docs. H1/H2/H6 FAIL; H3/H4/H5 PASS.

**Fix:** a separate docs-only FTS query (BM25 over `docs/**`) merged into the
result set; it is cheap (~50 ms) and needs no router. E48 measured docs-only
BM25 at **0.75 hit@1 / 1.00 hit@5** on 8 docs queries.
