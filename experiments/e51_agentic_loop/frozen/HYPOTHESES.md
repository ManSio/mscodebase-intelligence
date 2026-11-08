# E51 — frozen hypotheses (before the first run)

**Idea:** static repo map caps at ~40% (1k). Use a 3–4 step agentic retrieval
loop over the real SQLite index + PropertyGraph:
1. BM25 search original query;
2. read top files, extract identifiers, expand query, search again;
3. expand to graph neighbours of top files;
4. rank by RRF over steps + symbol overlap + graph proximity.

No embeddings, no LLM; deterministic policy. Token budget 8k; latency budget
5–10 s.

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | agent hit@1 > single BM25 hit@1 + 5 p.p. | <= +5 | PASS |
| H2 | agent hit@1 >= 0.75 | < 0.75 | **FAIL**? |
| H3 | agent hit@5 >= 0.85 | < 0.85 | PASS |
| H4 | p50 < 5,000 ms | >= 5,000 | PASS |
| H5 | agent hit@1 >= 0.95 | < 0.95 | **FAIL** |
| H6 | avg tool calls <= 5 | > 5 | PASS |
| H7 | avg context tokens <= 8,000 | > 8,000 | PASS |
| H8 | docs hit@1 >= 0.60 | < 0.60 | PASS |
| H9 | code hit@1 >= single code + 3 p.p. | < +3 | PASS |
| H10 | agent hit@5 >= single hit@5 + 5 p.p. | < +5 | PASS |

Baselines from E45/E31: production deterministic 0.688/0.771.
