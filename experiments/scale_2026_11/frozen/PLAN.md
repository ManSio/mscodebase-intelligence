# Scale panel — frozen plan (before the first run)

Date: 2026-11-10. Question: **does the 41-task panel generalize, or is it a
hand-picked sample that our numbers overfit?**

A panel of 16 tasks makes one task worth 6 points. Every rate we publish is a
point estimate with a huge interval (`REPORT.md`, Wilson). The way out is size,
but not size bought by writing more questions by hand: those would come from the
same head that wrote the hypotheses.

## Design

- **Generator, not author.** Tasks are derived from the index itself, seeded by
  the commit (`sha256(commit) -> random.Random`), so the same commit yields the
  same panel and a different commit yields a different one.
- **Buckets:**
  - `name` (160): "where is `<symbol>` defined" for a symbol with **exactly one**
    definition in the repo.
  - `qualified` (40): same, for `Class.method` names with a unique definition.
  - `negative` (40): the same question for a symbol that does not exist
    (`zz_<8 hex>`); the correct answer is "no rows".
- **Anchors (41):** the existing XERJ 24 + mcp_audit 17 panel, unchanged. They
  are the calibration: if the instrument drifts, the anchors move first.

Total: 281 tasks.

## Metrics

`top1`, `any@8`, `tokens-per-correct` (answer characters / 4 / number of top-1
hits), per bucket, with Wilson 95% intervals. Tokens are an estimate, not a
tokenizer measurement, and are labelled as such.

## Predictions (frozen)

| # | Prediction | Falsifier |
|---|---|---|
| S1 | generated `name` top-1 >= 0.60 | below 0.60 |
| S2 | `negative` yields no rows on >= 0.95 | any 3+ negatives return rows |
| S3 | anchors reproduce E65 `weights` (xerj 6/16, mcp_audit 11/17) within +/- 2 tasks | drift > 2 tasks |
| S4 | `qualified` top-1 <= `name` top-1 | qualified beats name |

S3 is the kill switch: if the anchors drift, the instrument is broken or the
code moved under it, and **no number from this run is published**.

## What this measures, and what it does not

Generated questions **contain the identifier**, so they measure the symbol
channel and the ranking around it. They say nothing about prose questions — that
is the `hints` contract (E64) and the metamorphic panel. A high generated rate
is not "search is good"; it is "exact names resolve", which is a necessary but
not sufficient property. Stating this here, before the run, so the result cannot
be oversold later.

The generator also cannot detect a symbol channel that is *too* eager: a
generated `name` task is passed by any tool that finds the name. The anchors and
the negative bucket are what keep it honest.
