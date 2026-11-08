# reranker_p3 probes — module-head / docstring anchor evidence

Persisted 2026-09-29 from `%TEMP%\opencode\` (byte-identical copies, hashes in SHA256SUMS).

## What

Two fresh-process direct-reranker probes that bypass retrieval and POST
straight to the reranker. Finding: the gold module-head/docstring chunk of
`src/core/artifact_gc.py` outscores every code chunk on holdout-style queries,
while the `_prune`-body code chunk scores a negative logit (P3 -0.99, R2 -2.60
in the eval path). Motivation for the P3 module-head anchor: guarantee the
docstring chunk a place in the pre-rerank pool.

## When / how run

- Both scripts stdlib-only (`urllib`), run as `python <script> <out.json>`.
- Model: BGE-M3 reranker served on `http://127.0.0.1:8081` (`/rerank`;
  probe 1 docstring says `/v1/rerank`, actual POST path in code is `/rerank`).
- No frozen eval-16 queries were used: probe queries are holdout-style
  P3/R2 variants (`ArtifactGC _cleanup_old_projects 30d 90d 7d retention_policy`
  etc.), disjoint from the frozen eval set.

## Files

- `probe_rerank.py` — probe 1: 6 queries x 5 passages (gold_doc head 800 chars
  of `src/core/artifact_gc.py`, gold_code `_prune` body chars [1500:2300],
  distractors engine/settings/diary heads). Output `rerank_probe_run1.json`.
- `probe_rerank2.py` — probe 2: every AST-plausible chunk of `artifact_gc.py`
  (module_head + per-def chunks with scope header, 800 chars) on P3/R2 queries.
  Output `rerank_probe_run2.json`.
- `rerank_probe_run1.json` — 6/6 queries rank `gold_doc` #1 (sigmoid 0.69–0.99).
- `rerank_probe_run2.json` — `module_head` top on both queries
  (P3 +0.57, R2 +0.43); all code chunks negative except `prune_stale_artifacts`
  on R2 (+0.27).

## Citation rule

Rerank numbers are cited as
`experiments/reranker_p3/rerank_probe_run{1,2}.json` + `EXPERIMENTS_LOG.md:2809`
(raw eval logits P3 -0.99 / R2 -2.60 on the pre-rerank pool) — never
`judged_raw.json` for rerank scores.

## Frozen prompt

None — queries are listed verbatim in the scripts and in `rerank_probe_run1.json`
(`queries.<id>.query`). No LLM judge involved.
