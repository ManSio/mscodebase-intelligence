# P3 module-head anchor — preregistration (2026-09-29)

Status: PREREGISTERED — written BEFORE implementing the anchor. No numbers
invented here; thresholds/caps referenced are the existing ones
(`_O1_ANCHOR_TOTAL`, `MAX_RERANKER_INPUT=30`, `MIN_RERANK_SCORE=0.3` untouched).

## Hypothesis

P3 (`src/core/artifact_gc.py` gold file below threshold) is a pool-entry /
ranking problem of the same family as P2: the chunk the reranker scores
highest (module-head/docstring) never reaches the reranker, while the code
chunk that does reach it scores a negative logit and dies at the threshold.

## Decision rule (verbatim)

"anchor a file's module-head/docstring chunk into the pre-rerank pool iff it
scores above threshold on holdout queries; falsified if (i) docstring chunks
do not outscore code chunks on holdout, (ii) anchoring regresses holdout H-set,
(iii) pool cost exceeds caps".

## Reading of the three clauses

- (i) is checked by the persisted probes
  (`rerank_probe_run1.json`: gold_doc #1 on 6/6 holdout-style queries;
  `rerank_probe_run2.json`: module_head top on P3/R2, code chunks negative).
- (ii) is checked by the no-regression holdout H1–H12 + P/R + doc-control
  gate (fresh-process discipline — reranker-cache trap).
- (iii) is checked structurally: anchors bounded by the existing caps
  (`_O1_ANCHOR_TOTAL`, `MAX_RERANKER_INPUT=30`).

## Scope

- Validate on holdout only — NEVER the frozen eval-16.
- `MIN_RERANK_SCORE=0.3` untouched (threshold sweep on the eval set was
  explicitly refuted in `EXPERIMENTS_LOG.md:2815-2816`).
- Minimal diff extending the P2 `_anchor_identifier_chunks_async` precedent
  (`engine.py:772-805`), same style.
