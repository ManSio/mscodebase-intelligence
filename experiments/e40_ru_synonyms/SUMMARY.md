# E40 — Russian → English code-term synonym expansion

**Panel:** E30 48 queries (mostly Russian NL), corrected index, E33 demote ON,
P3 off, no reranker. New `src/core/search/synonyms_ru.py` (curated RU_EN +
RU_PHRASES); query variants up to 4, merged by RRF.

| Arm | hit@1 | hit@5 | MRR | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| baseline | 0.688 | 0.771 | 0.713 | 159 ms | 289 ms |
| ru_synonyms | 0.688 | 0.771 | 0.713 | 176 ms | 356 ms |

## Hypothesis outcomes

| # | Hypothesis | Result |
|---|---|---|
| H1 | RU synonyms +2 hit@1 | **FAIL** — unchanged |
| H2 | RU synonyms +1 hit@5 | **FAIL** — unchanged |
| H3 | p50 < 120 ms | **FAIL** — 159–176 ms (baseline measurement noise) |
| H4 | hit@1 >= 0.75 | **FAIL** — 0.688 |
| H5 | hit@1 >= 0.95 | **FAIL** — 0.688 |
| H6 | no precision loss | **PASS** — unchanged |

## What this means

1. **RU ↔ EN synonym expansion is neutral on this panel.** The added variants
   return the same top-5; RRF merges duplicates and the fused order is unchanged.
2. The E28 queries already contain enough code identifiers / the index contains
   Russian docstrings, so the English synonym bridge adds no new recall.
3. The dictionary is still useful as a utility (e.g., for other projects), but
   it is **off by default** and not a quality lever here.

## Final picture

Deterministic pipeline: **0.688 hit@1 / 0.771 hit@5 / 84 ms** (P3 off).
Tested and rejected/neutral:
- code-aware BM25 (E32) — neutral;
- FTS5 field weights (E33) — neutral;
- demote non-code (E33) — **+3 hit@1** (the only win);
- graph/PRF (E34/E34b) — null;
- chunking 32/64/128 (E37) — null;
- RU synonyms (E40) — null;
- rerankers MiniLM/BGE-base/BGE-M3/Qwen3 (E35/E38/E39) — all worse or unusable.

**95% hit@1 is not achievable on this 48-query panel with the tested CPU
approaches.** Further gains need a different architecture (code-specific dense
index + GPU) or a fine-tuned code ranker, not another lexical/synonym tweak.
