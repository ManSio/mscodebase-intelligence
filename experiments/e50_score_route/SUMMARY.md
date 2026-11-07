# E50 — BM25 score-margin router

**Idea:** route docs when `doc_rel > t * code_rel`; no keywords. Thresholds
0.8–2.0; held-out odd/even split.

## Results (all 48)

| Arm | 1k | 2k | 4k |
|---|---:|---:|---:|
| base | 0.271 | 0.458 | 0.562 |
| docs | 0.104 | 0.125 | 0.167 |
| oracle | 0.375 | 0.583 | 0.729 |
| route@0.8–2.0 | 0.104 | 0.125 | 0.167 |

p50 = 460 ms.

Code-gold (40): route 0/0/0; docs-gold (8): route 0.625/0.750/1.000.
Docs queries routed: **8/8 for every threshold** (score margin never says "code").
Held-out t=0.8: odd 0.125, even 0.083, full 0.104.

## Verdict

- **BM25 scores are not a routing signal**: docs text matches natural-language
  queries better than code identifiers, so `doc_rel > t*code_rel` is always true.
- All code queries get routed to docs → code coverage collapses to 0.
- Oracle ceiling 0.375/0.583/0.729; 95% impossible.
- H1–H7 FAIL except H8 (460 ms < 5 s).

## Lesson

Routing needs **semantic intent classification**, not lexical scores. With a
5–10 s budget, use an LLM/classifier or an agentic loop; a static map alone
cannot reach 95%.
