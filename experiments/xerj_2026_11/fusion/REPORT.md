# Fusion A/B — result (E65)

Frozen before the run: `frozen/PLAN.md` (three arms, five criteria) and
Amendment 1 (the owner's decision that latency is not a criterion). Harness
attacks and the three aborted runs: `REDTEAM.md`. Every claim below is a command
in `LEDGER.md`.

This is the **fourth** attempt. The first three were stopped before publishing:
two for policy bugs in the arms (demotion cap, arrival-order tie-break), one for
a scoring bug in the harness (panel gold is a list; every XERJ task scored as a
miss), and the third measurement for a formula that did not match the frozen
spec (`definition` and `symbol` merged into one vote after a review round that
assumed they were one lookup — they are two different searches).

## Result

Arms: 53 asks (XERJ 24 + mcp_audit 17 + metamorphic 12) x 3 arms x 3 repeats,
arms rotated per task, per-task majority.

```
bucket                n   top1 weights/rrf/norm   any weights/rrf/norm
xerj/positive        16    6/ 5/ 6               10/10/10
xerj/ambiguity        4    0/ 0/ 0                2/ 2/ 2
xerj/negative         4    4/ 4/ 4                4/ 4/ 4
mcp_audit/positive   17   11/ 6/ 9               14/13/14
metamorphic/positive 12    4/ 4/ 5                8/ 7/ 8
-----------------------------------------------  top1 21 / 15 / 20
```

Wilson 95% (`python experiments/xerj_2026_11/wilson.py`):

```
xerj top1, weights        6/16 = 0.375 [0.18, 0.61]
xerj top1, rrf            5/16 = 0.312 [0.14, 0.56]
xerj top1, norm           6/16 = 0.375 [0.18, 0.61]
mcp_audit top1, weights  11/17 = 0.647 [0.41, 0.83]
mcp_audit top1, rrf       6/17 = 0.353 [0.17, 0.59]
mcp_audit top1, norm      9/17 = 0.529 [0.31, 0.74]
mcp_audit any@8, rrf     13/17 = 0.765 [0.53, 0.90]
metamorphic top1, weights 4/12 = 0.333 [0.14, 0.61]
metamorphic top1, norm    5/12 = 0.417 [0.19, 0.68]
negatives (no rows)       4/4  = 1.000 [0.51, 1.00]
```

## Frozen criteria

| # | Criterion | Result |
|---|---|---|
| F1 | RRF does not lose `any` on XERJ or mcp_audit | **FAIL** — `MSC03` lost `any` (`14 -> 13` on mcp_audit) |
| F2 | RRF gains >= 2 tasks of top-1 | **FAIL** — `-6` tasks (21 -> 15) |
| F3 | `norm` does not beat RRF by >= 2 | **FAIL** — `norm` is +5 over RRF (20 vs 15) |
| F4 | No negative task gains a row | PASS (4/4 empty in every arm) |

Per the kill rule frozen before the run, **the shipped formula stays
`weights`**. Nothing about ranking changes in this PR.

## What moved, task by task

```
rrf   BLA01  top1 True->False   norm  BLA02  top1 True->False
rrf   BLA02  top1 True->False   norm  HTT04  top1 True->False
rrf   BLA04  top1 True->False   norm  MSC03  top1 True->False
rrf   MSC02  top1 True->False   norm  P02    top1 True->False
rrf   MSC03  top1 True->False   norm  MSC04  top1 False->True
rrf   MSC03  any  True->False   norm  P12    top1 False->True
rrf   P05    top1 True->False   norm  T4-ru  top1 False->True
rrf   T2-en  any  True->False
```

RRF wins nothing and loses six top-1 tasks plus two `any`. `norm` trades four
losses for three wins.

## Why RRF loses on this corpus (mechanism, not opinion)

1. **RRF throws the score away.** In `weights` the search channel contributes its
   own `1/(idx+1)` curve and grep adds `+0.5` for a `raise` line. In RRF only the
   position inside each channel counts, so an exact hit and a weak hit 60 rows
   apart are worth the same. The mcp_audit collapse (`11 -> 6` top-1) is exactly
   where that signal mattered: those questions are answerable by an exact
   identifier.
2. **Consensus favours declarations.** A definition row is found by more channels
   than a usage row, so RRF pushes the definition up — the opposite of what a
   reference question needs. The previous, wrong variant of this experiment merged
   `definition` and `symbol` into one vote; that only *masked* the effect (RRF
   looked like `-2` instead of `-6`). Removing the merge made RRF worse, which is
   the direction the mechanism predicts.
3. **RRF's first hit of every channel is exactly `1/60`**, so top-1 inside a tie
   group is decided by the tie-break. `P12`/`T4-ru` gaining under `norm` while
   `P05` loses under `rrf` has that signature.

## Guards (printed by the runner, not hand-written)

```
invalid runs: {'weights': 0, 'rrf': 0, 'norm': 0}
scored tasks: {'weights': 53, 'rrf': 53, 'norm': 53} (frozen panel 53)
non-deterministic rows per arm: {'weights': 4, 'rrf': 4, 'norm': 1}
arms return different rows somewhere: True
latency (note only): mean 2.75 / 2.79 / 2.79 s
```

Note the two different stability numbers: the **metric** (`top1`/`any`) is stable
across repeats in every arm (0 flaky), while the **returned row list** drifts on
4/4/1 tasks — the corpus is still moving under the tool (index freshness, the
change-notifier). `norm` is the most stable arm and still loses on top-1.

## Observation that needs its own measurement (not claimed)

The control arm reads `mcp_audit 11/17` here and `9/17` in E62. Between the two
runs the only merge change is the deterministic tie-break, so the tie-break is a
plausible cause — 2 tasks is inside the noise for n=17 (`[0.41, 0.83]` vs
`[0.31, 0.74]` overlap heavily). It reproduced across two independent 3-repeat
runs of this experiment (11/17 both times), which makes it worth its own
measurement rather than a claim: re-run `evidence_gate/run_gate.py` on this build
and compare its control arm with the stored E62 rows.

## Threats

- The metamorphic panel (12 asks) was written by the same author as the
  hypotheses: it is a control, not an independent sample.
- One `InvestigateTool` per root serves all arms, so the first call of a session
  is colder. Rotation spreads that, it does not remove it.
- Five criteria were frozen; no "best bucket" is picked after the fact.
- `n` is 16/17/12: a one-task difference is 6 points on XERJ. The verdict rests
  on the direction of the whole panel and on the mechanism above, not on a rate.

## What this means for the plan

The ranking stack is not the binding constraint: a fundamentally different
fusion formula loses by six tasks on the panel the product is measured on. Per
the rule frozen before the run ("if RRF gains <= 1 task, stop tuning ranking"),
ranking work stops here. The next lever is the one with the largest known gap —
panel size and public reproducibility (`n >= 200`, generated tasks with anchors,
a release) — not a fourth weighting scheme.
