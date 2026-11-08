# E44 — frozen hypotheses (before the first run)

**Idea:** MSCodeBase is agent-facing. Instead of asking the retriever to parse a
Russian NL question, the agent supplies several search formulations (keywords,
identifiers, English terms, concept terms). This is the "agent rewrites the
query" path.

Panel: E30 48 queries, corrected index, E33 demote ON, P3 off, no reranker.
Frozen rewrites: `QUERIES_REWRITTEN.jsonl` sha `d1a1e108…` (up to 5 per query).

Arms:
- baseline: current `_expand_query` (English synonyms only)
- keywords: only the stopword-stripped query
- identifiers: only code identifiers extracted from the query
- agent_all: all rewrites (up to 5), fused by RRF

| # | Hypothesis | Falsifier | Expectation |
|---|---|---|---|
| H1 | agent_all improves hit@1 by >= 5 | delta < 5 | PASS |
| H2 | agent_all improves hit@5 by >= 3 | delta < 3 | PASS |
| H3 | agent_all p50 < 300 ms | p50 >= 300 ms | PASS |
| H4 | agent_all hit@1 >= 0.75 | hit@1 < 0.75 | **FAIL** (95% far) |
| H5 | agent_all hit@1 >= 0.95 | hit@1 < 0.95 | **FAIL** |
| H6 | identifiers-only improves hit@1 by >= 3 | delta < 3 | **FAIL** (identifier extraction is noisy) |

No graph stage; the rewrites are the only change.

