# Rewrite gate — three-arm report (on / off / smart)

Date: 2026-11-10. Base: `main` @ `78a8507` (evidence gate merged). Predictions
were frozen in `frozen/REWRITE.md` before the run.

## Question

The gate that asks a Russian question for an identifier (XERJ N03) also hid
real questions: measured with the gate on, it bought N03 (8 neighbour rows → 0)
and cost P16 (its correct top-1). Is there a rule that keeps the N03 property
without the cost?

## Arms

One process, one index, 27 asks (XERJ 24 + 3 `mcp_audit` RU), interleaved per
task, one run per arm (the rule is deterministic; repeats were used for the
retrieval layer in E58, not here):

- `on` — no code-shaped token → ask for an identifier (shipped default until now);
- `off` — neighbours with a verdict;
- `smart` — the same as `on`, but only when the question also names a
  proper-noun-like Latin word (`[A-Z][a-z]{2,}`: `Corpus`, `Hub`). Acronyms
  (`LSP`) and dotted tokens (`progress.json`) do not qualify, and anything
  backticked or code-shaped passes.

## Result

Per-task majority over **3 repeats per arm** (retrieval order is not stable;
each arm ran the same 27 asks in rotated order):

| arm | gated / 27 | non-negative top1 (n=23) | non-negative any (n=23) | negative rows (n=4) | RU any (n=3) |
|---|---:|---:|---:|---:|---:|
| `on` | 9 | 0.174 | 0.478 | 0 | 0.000 |
| `off` | 0 | 0.217 | 0.522 | 8 | 0.000 |
| **`smart`** | **1** | **0.217** | **0.522** | **0** | **0.000** |

Per task (`G` = gated, then top1/any):

```
id      on  off smart        id      on  off smart
P01     -11 -11 -11          N01     -11 -11 -11
P02     -11 -11 -11          N02     -11 -11 -11
P03     -00 -00 -00          N03     G11 -00 G11
P04     G00 -00 -00          N04     -11 -11 -11
P05     -01 -01 -01          MSCRU1  G00 -00 -00
P06     G00 -00 -00          MSCRU2  G00 -00 -00
P07     -01 -01 -01          MSCRU3  G00 -00 -00
P08     -11 -11 -11
P09     -01 -01 -01
P10     -01 -01 -01
P11     -11 -11 -11
P12     -01 -01 -01
P13     -00 -00 -00
P14     G00 -00 -00
P15     G00 -00 -00
P16     G00 -11 -11
A01     -01 -01 -01
A02     -01 -01 -01
A03     -00 -00 -00
A04     -00 -00 -00
```

`smart` gates exactly one query (N03) and returns rows for the other 26.

### The one difference between `smart` and `off` is P16, and its rank is not stable

P16 is the only task where `smart`/`off` differ from `on` in the table. Rows are
stable (`8` every run for both); the *rank* is not:

```
3-run majority (this experiment):  off 3/3 hit, smart 3/3 hit
5 repeats 10 minutes later:        off 0/5 hit, smart 0/5 hit (gold not in top-8)
```

The corpus/index was reindexed between the two checks (the host's freshness
pass), and this docs question is sensitive to that. So the `+0.043` in the rates
is an index-state sample, not a property of the rule. What is stable: `on` hides
these questions, `smart`/`off` show the rows with a verdict.

## Frozen predictions

| # | Prediction | Verdict |
|---|---|---|
| R1 | `smart` gates exactly one query (N03) | **pass** (1/27) |
| R2 | `smart` keeps N03 at zero rows | **pass** (0) |
| R3 | `smart` loses no hit vs `off` | **pass** (0.217 / 0.522 = `off`, majority) |
| R4 | `smart` restores P16 (top1 True, rows present) | **partial** — rows are restored and stable (8 every run); the rank is not (3/3 in this run, 0/5 ten minutes later) |
| R5 | RU questions are un-gated in `smart` and still miss the gold | **FAIL as predicted** — un-gated, `any` 0.000; retrieval, not the gate, is the limit |

## Decision

Default changed to `smart`. `on` stays available (`MSCODEBASE_ASK_REWRITE=1`),
`off` stays available (`=0`). The 2026-11-09 rule is not deleted; it is no
longer the default.

The decision does **not** rest on the +1 in the table. It rests on the stable
part: `smart` keeps exactly the one behaviour the gate was built for (N03) and
stops withholding rows for the other 26 questions, where `on` produced silence
with no measured benefit. Every non-answer still carries a verdict, so a
neighbour list is never presented as an answer.

## Threats

- **Three repeats per arm, majority.** The rule is a pure function of the query
  string, so the gate itself is deterministic; the repeats exist because
  retrieval is not (P16's rank moved between index states, and E58 saw MSC04's
  neighbour order move between repeats).
- **One panel, 27 asks.** The positives that `smart` restores are Russian prose
  questions; another panel could contain a question that names a proper noun
  for a real entity and is now gated ("Где Corpus Hub API?"). Mitigation: a
  backticked, dotted or lowercase code term always passes.
- **No corpus check.** A proper noun that *does* exist in the corpus (e.g. a
  real product name) would still be gated. A bigram lookup would need a query
  inside a pre-retrieval gate; not implemented, because the measured panel has
  no such case and the gate is conservative (it hides, never fabricates).
- **Held-out panel is English**, so it cannot validate the Russian rule at all.

## Reproduce

```bash
python experiments/xerj_2026_11/evidence_gate/probe_rewrite_design.py
python experiments/xerj_2026_11/evidence_gate/probe_rewrite_arms.py
```
