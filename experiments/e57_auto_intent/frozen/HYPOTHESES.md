# E57 — frozen hypotheses (before the first run)

**Goal:** the tool, not the human, chooses docs vs code. Cheap lexical
`auto_detect_intent` (no LLM) routes to `search_docs` or code quality.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | auto docs hit@1 (same-basename) >= 0.60 | < 0.60 | PASS |
| H2 | auto overall hit@1 >= 0.72 | < 0.72 | PASS |
| H3 | auto code hit@1 >= 0.70 | < 0.70 | PASS |
| H4 | auto overall hit@1 >= 0.688 + 3 p.p. | < +3 | PASS |
| H5 | p50 < 5,000 ms | >= 5,000 | PASS |
| H6 | false-positive docs intent on code gold <= 4 | > 4 | PASS |
| H7 | auto overall hit@1 >= 0.95 | < 0.95 | **FAIL** |
| H8 | auto hit@5 >= 0.85 | < 0.85 | PASS |

Baseline code quality: 0.688/0.771; code 0.825/0.900; docs 0/0.125.
