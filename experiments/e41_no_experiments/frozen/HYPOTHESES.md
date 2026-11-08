# E41 — frozen hypotheses (before the first run)

**Trigger:** diagnostic showed `experiments/4A_unit_of_return/frozen/f5/queries.md`
(and other experiment query files) ranking above gold code because the query
panel itself is indexed. This is retrieval pollution, not a ranking failure.

Panel: E30 48 queries, corrected index, E33 demote ON, P3 off, no reranker.

Arms:
- baseline: current store (includes `experiments/`)
- no_experiments: same store minus every `file_path` starting with `experiments/`

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | excluding experiments improves hit@1 by >= 5 | delta < 5 | PASS |
| H2 | excluding experiments improves hit@5 by >= 3 | delta < 3 | PASS |
| H3 | p50 stays < 150 ms | p50 >= 150 ms | PASS |
| H4 | no_experiments reaches hit@1 >= 0.80 | hit@1 < 0.80 | **FAIL** (95% still far) |
| H5 | no_experiments reaches hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |

No graph stage (`_symbol_index=None`) to isolate the store change.
