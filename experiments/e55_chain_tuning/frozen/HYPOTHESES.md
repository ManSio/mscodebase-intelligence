# E55 — frozen hypotheses (before the first run)

**Question:** after graph rebuild + index cleanup, which real chain path and
which cheap flags give the best result without LLM?

Arms: `hybrid_search_async`, `search_with_mode(fast/quality/deep)`, and
quality with `demote_off`, `demote_intent`, `ru_synonyms`, `p3_anchor`.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | fast hit@1 >= 0.70 | < 0.70 | PASS |
| H2 | quality hit@1 >= 0.70 | < 0.70 | PASS |
| H3 | quality code hit@1 >= 0.85 (graph rebuilt) | < 0.85 | PASS |
| H4 | docs hit@1 = 0 for every arm | > 0 | PASS |
| H5 | fast p50 < 1,000 ms | >= 1,000 | PASS |
| H6 | quality p50 < 5,000 ms | >= 5,000 | PASS |
| H7 | ru_synonyms improves hit@1 by >= 2 p.p. | < +2 | **FAIL**? |
| H8 | demote_intent improves docs hit@5 > 0 | 0 | PASS |
| H9 | best hit@1 >= 0.95 | < 0.95 | **FAIL** |
| H10 | best hit@1 > 0.688 + 5 p.p. | <= +5 | **FAIL**? |

Clean baseline (E52, empty graph): 0.688/0.750; code 0.825/0.900; docs 0/0.
