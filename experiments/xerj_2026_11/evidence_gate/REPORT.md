# Evidence gate — control/treatment report

Date: 2026-11-10. Base: `main` @ `0e8d131`. The measured code is this PR's
branch (`score: verify investigate rows before presenting them`).

Predictions and kill criteria were frozen in `frozen/HYPOTHESES.md` **before**
the first run. Nothing in that file was edited after seeing numbers; where a
criterion fired, the rule was fixed, not the criterion.

## Design

One process, one index, one commit. The arms differ only in the env flag:

- **control** `MSCODEBASE_EVIDENCE_GATE=0` — the same commit with the gate off;
- **treatment** `MSCODEBASE_EVIDENCE_GATE=1` — evidence gate + promotion of a
  verified declaration above name matches.

The flag does **not** cover the rewrite-gate fixes that ship in the same commit
(`progress.json`/backtick handling): those apply to both arms. Verified: the
only panel question whose behaviour differs from the 2026-11-09 build is P05
(`progress.json`), in both arms.

Arms are **interleaved per task** and repeated **3 times** per arm, with the
order alternating by task and run. Two sequential sweeps were tried first and
discarded: that design measured a 12 s slow-down on six consecutive tasks
because the host's indexer was writing, so it would have blamed the gate.
Repeats exist because the channel set is timing-sensitive (grep has a 15 s
budget). Metrics are per task by **majority over repeats**; a tie counts as a
miss.

Panels: XERJ 24 (16 positive, 4 ambiguity where *both* golds are required,
4 negative where any `file:line` row is a false positive) + `mcp_audit` 17
(6 EN + 3 RU on this repo, 4 on `black`, 4 on `httpbin`). Task files are
pinned by `frozen/MANIFEST.sha256`.

## Result (current defaults, 3 repeats per arm, E62)

| bucket | n | top1 control | top1 treatment | any control | any treatment | flaky tasks |
|---|---:|---:|---:|---:|---:|---:|
| xerj/positive | 16 | 0.312 | **0.375** | 0.625 | 0.625 | 0 |
| xerj/ambiguity | 4 | 0.000 | 0.000 | 0.500 | 0.500 | 0 |
| xerj/negative | 4 | 1.000 | 1.000 | 1.000 | 1.000 | 0 |
| mcp_audit/positive | 17 | 0.529 | 0.529 | 0.824 | 0.824 | 0 |

`flaky` counts tasks whose `top1` or `any` moved between repeats of one arm:
zero in this run.

**What changed:** exactly one task, top-1 only:

```
xerj P01  top1 False -> True   ("Где определяется `build_call_graph`…")
```

A verified declaration existed below rank 1 and the promotion moved it up. No
task lost `any`, no row set changed on negatives, no ambiguity gold was lost,
and `mcp_audit` is identical in both arms.

The table moved from 0.250/0.312 (E58) to 0.312/0.375 because two later changes
became the shipped defaults: E61 (scripts/examples demotion) and E62 (chunk-line
locator + second-identifier `exact`). The gate's own delta is still exactly one
task (P01, +0.0625); the absolute rates are a snapshot of the current defaults.

An earlier measurement (under the old `on` rewrite default) showed a second gain
(P07). That one was an artefact and is **not** claimed: the promoted row was
`impact = si.get_impact_analysis(...)` — a local variable named after the query
word — and `impact` was counted as a call-graph edge. Both are fixed (assignment
verification is module/class-level only; `impact` is a risk summary, not an
edge).

## Kill criteria

| # | Criterion | Verdict |
|---|---|---|
| H1 | `any@8` does not drop in any bucket | **pass** (no bucket changed) |
| H2 | `negative` does not change | **pass** (1.000 in both, rows 0 in both) |
| H3 | `top1` does not drop | **pass** on the kill condition (+0.062 on xerj/positive, 0 elsewhere); the predicted mcp_audit improvement did **not** materialize (0.412 in both arms) |
| H4 | `ambiguity` keeps both golds | **pass** (0.500 in both) |
| H5 | latency mean ≤ +0.25 s, p95 ≤ +0.60 s | **pass** after one fix, see below |
| H6 | determinism: repeats of a task give the same verdict and first row | **pass** in the final run (41 tasks × 3, 0 flaky); an earlier run moved one neighbour order — see below |

**Overall:** H1–H6 pass under the frozen thresholds in the final run (H5 after
one fix, see below). No task lost a hit, no negative gained a row.

### H6: passed; an earlier run moved one neighbour order

The frozen criterion names no task ids: *"two treatment runs on 4 fixed tasks
give the same verdict and the same first row"*. Checked on the four intended
tasks (P01, P02, N01, MSC01), all three repeats are identical. While adding the
§19.1 falsifier column the wording was broadened to *all* tasks; an **earlier**
run under that reading moved the first row of `MSC04`:

```
run1 abstain 0.10  run_all.py
run2 abstain 0.10  run_all.py
run3 abstain 0.10  check_knowledge.py
```

Verdict and confidence were identical in all three; only the ordering of two
unverified neighbours changed, and no channel was reported as degraded. The
final run has zero flaky tasks. That instability is the retrieval layer's tie
order — the gate does not reorder on `abstain`/`caveat` — and it is why repeats
exist and why the gate has its own determinism guard:
`test_assess_is_deterministic_on_fixed_rows` (10 repeats on fixed rows, one
identical report). End-to-end ordering of neighbour rows stays a property of
retrieval and is reported, not hidden.

### H5 fired once, and the fix is part of the change

First interleaved run: mean **+0.27 s** — 0.02 s over the frozen threshold.
Cause: the gate parsed every candidate file with `ast`, including the seven
neighbours per answer that define nothing. Fix: a file is parsed only when the
line or the symbol index says a definition can be there; for Python the parser
is then authoritative (a declaration-shaped line inside a docstring is not a
declaration). The frozen threshold was not touched. Final, with repeats:

```
control    mean=2.57s  p95=3.80s  (n=123)
treatment  mean=2.67s  p95=3.90s  (n=123)
delta      mean=+0.10s p95=+0.10s
```

## Verdict distribution (treatment, run 1 per task, E62)

| bucket | answer | caveat | abstain | ask_rewrite |
|---|---:|---:|---:|---:|
| xerj/positive | 3 | 7 | 6 | 0 |
| xerj/ambiguity | 3 | 1 | 0 | 0 |
| xerj/negative | 0 | 0 | 3 | 1 |
| mcp_audit/positive | 4 | 9 | 4 | 0 |

Three of the four ambiguity tasks are `answer`; A03 ("staleness") is `caveat`
because the question names a concept, not a symbol — the rows (`check_staleness`)
are occurrences, and the gate says so instead of pinning one as "the"
definition. The four XERJ negatives are `abstain`/`ask_rewrite` with zero rows,
i.e. the frozen "no false positive" rule still holds.

The `mcp_audit` split shifts between measurements (4/4 → 4/4 → 4/9 answer to
abstain over three runs): those questions point at files that were being edited
while the panels ran, so `fresh` correctly demotes them (`exact` + stale =
0.15 → `abstain`). The distribution is descriptive, not a metric; `top1`/`any`
were stable across every run.

Under the `smart` rewrite default no XERJ positive is `ask_rewrite` any more:
the four Russian prose questions that the old `on` rule hid are back as
`abstain` with neighbour rows and an explicit "no row carries evidence" note.

## Held-out panel (different corpora, tasks written before the gate existed)

`probe_heldout.py` runs the 12 unique tasks from `frozen/gold_external*.json`
(itsdangerous + iniconfig, pinned, indexed separately; `gold_external_v2.json`
supersedes v1 for the three tasks it re-froze). These tasks were written on
2026-11-08 for the search-channel experiment; they were not used to tune the
gate.

| arm | n | top1 | any@8 | verdicts |
|---|---:|---:|---:|---|
| control | 12 | 1.000 | 1.000 | no verdict lines (gate off) |
| treatment | 12 | 1.000 | 1.000 | answer 12 |

No task changed. This is the no-harm check: on a corpus and a task set the gate
never saw, verification neither loses nor reorders a hit. It is **not** a
quality claim — that panel is already at 1.000 for both arms, so it cannot show
an improvement.

## Cost of the ask-for-identifier gate (measured, not assumed)

`probe_rewrite.py` switches `MSCODEBASE_ASK_REWRITE` with the evidence gate on,
27 tasks (XERJ 24 + the 3 RU questions), interleaved:

| arm | non-negative top1 (n=23) | non-negative any (n=23) | negative rows, mean (n=4) | RU any (n=3) |
|---|---:|---:|---:|---:|
| rewrite ON (default) | 0.174 | 0.478 | 0.00 | 0.000 |
| rewrite OFF | 0.217 | 0.522 | 2.00 | 0.000 |

(n=23 = 16 XERJ positive + 4 XERJ ambiguity + 3 RU; the ambiguity tasks are
included because the gate can fire on them too.)

Reading: the gate buys **N03** (8 neighbour rows → 0, the only negative that
ever printed rows) and costs **P16** — a natural Russian question whose correct
top-1 (`AGENTS.md`) was already found. It costs nothing else that mattered:
the three RU questions miss the gold in *both* arms, so the gate hides wrong
neighbours, not a right answer.

The default stays ON because that was the owner's decision in PR #95, but the
trade is now explicit and switchable without a code change. The evidence gate
makes the alternative safe: with `MSCODEBASE_ASK_REWRITE=0` the same question
comes back with `verdict: abstain` and rows marked as neighbours.

## Threats to validity

- **Small panels.** One task is 6.25% of XERJ positives; the +0.0625 delta is
  exactly one task (P01). The per-task table is the real result, not the rate.
- **Absolute rates drift with the index state.** P16 (a docs question in the
  positive bucket) was retrievable during the run and is not in a later 5-repeat
  check (0/5 for gold in top-8). It sits in both arms, so the delta is
  unaffected; the bucket rates are a snapshot, and the P01 delta is the claim.
- **Not blind.** P01/P07 were inspected during development (they motivated the
  promotion rule). The held-out external panel is the mitigation, and it shows
  no harm, but it is too easy to show a gain.
- **File-level gold.** `any@8`/`top1` score files, not lines; a right file with a
  wrong line counts as a hit. The gate's line-level check is stricter than the
  metric.
- **Shared host.** The MCP host was running during the measurement (its DB lock
  is why the gate uses a read-only batch). Interleaving is what keeps that from
  biasing the arms, not isolation.
- **Rewrites are not scored as answers.** `ask_rewrite` and `abstain` tasks are
  misses by construction; the verdict distribution is reported separately so a
  "no answer" is not read as a retrieval failure.
- **`file:0` rows.** A row with no line (a module constant the symbol index does
  not carry) stays `:0`; the gate verifies a line only when one exists and does
  not invent one. One such row appears in the black panel (`const.py:0`).
- **Decorator without an index line.** A row that sits on `@decorator` is
  verified only when the symbol index knows the declaration line; without it
  the line check sees `@cache` and the file is not parsed. Conservative — no
  false answer — and it costs recall only on such rows.

## What this does not prove

- It does not improve recall: `any` is unchanged in every bucket.
- It does not claim an absolute quality win over grep; the comparison is
  gate-on vs gate-off of the same tool.
- The `mcp_audit` panel showed no change at all; the gain is concentrated in
  the XERJ definition questions where a declaration was already retrieved.

## Reproduce

```bash
python experiments/xerj_2026_11/evidence_gate/run_gate.py --runs 3
python experiments/xerj_2026_11/evidence_gate/compare.py
python experiments/xerj_2026_11/evidence_gate/probe_heldout.py
python experiments/xerj_2026_11/evidence_gate/probe_rewrite.py
```
