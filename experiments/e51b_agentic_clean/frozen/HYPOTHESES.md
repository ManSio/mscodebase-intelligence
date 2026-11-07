# E51b — frozen hypotheses (before the first run)

**Reason for E51b:** E51 exposed a contamination: `experiments/4A_unit_of_return/
frozen/f5/queries.md` is in the index and contains the same panel queries, so BM25
returns it as top-1 for most queries. E51b excludes all `experiments/` paths from
retrieval and re-runs the identical policy.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | agent hit@1 > single BM25 hit@1 + 5 p.p. | <= +5 | PASS |
| H2 | agent hit@1 >= 0.70 | < 0.70 | **FAIL**? |
| H3 | agent hit@5 >= 0.85 | < 0.85 | PASS |
| H4 | p50 < 5,000 ms | >= 5,000 | PASS |
| H5 | agent hit@1 >= 0.95 | < 0.95 | **FAIL** |
| H6 | avg tool calls <= 5 | > 5 | PASS |
| H7 | avg context tokens <= 8,000 | > 8,000 | PASS |
| H8 | docs hit@1 >= 0.50 | < 0.50 | PASS |
| H9 | code hit@1 >= single code + 3 p.p. | < +3 | PASS |
| H10 | agent hit@5 >= single hit@5 + 5 p.p. | < +5 | PASS |
| H11 | filtered single hit@1 > E51 contaminated 0.458 | <= | PASS |
