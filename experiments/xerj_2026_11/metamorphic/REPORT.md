# Metamorphic triples — result

Frozen before the run: `frozen/TASKS.md`. 4 base tasks × (name / ru / en) = 12
asks; gold file fixed per task.

## Result

```
per form
  name top1=3/4 any=4/4
  ru   top1=0/4 any=2/4
  en   top1=1/4 any=2/4

per base
  T1: name=Y  ru=n  en=n
  T2: name=Y  ru=n  en=n
  T3: name=Y  ru=n  en=Y
  T4: name=n  ru=n  en=n
```

## Frozen predictions

| # | Prediction | Verdict |
|---|---|---|
| M1 | `name` hits every base at top-1 | **fail, but see below** — T4 top-1 is `graph_adapter_pure.py:477 PureGraphMixin.get_call_chain`, a real definition; the gold `symbol_index.py:353` is the *second* real definition of the same method name |
| M2 | `ru` is worse than `name` on ≥2 of 4 | **pass** (0/4 vs 3/4) |
| M3 | `en` is better than `ru` on ≥2 of 4 | **fail** — `en` is better on 1 (T3); `en` 1/4 vs `ru` 0/4 |
| M4 | an `answer` verdict only for hits | **pass** in the observed rows |

## Hints: the host is the multilingual layer

The server should not carry dictionaries for every language. The host model
already knows the code-shaped names, whatever language the user typed. With the
name passed as a hint (`investigate(query, hints=["get_progress_file"])`) all
three forms reach the same level:

```
per form, no hints        per form, name passed as hint
  name 3/4 top1              name 3/4
  ru   0/4 top1              ru   3/4
  en   1/4 top1              en   3/4
any: 4/4 · 2/4 · 2/4         any: 4/4 · 4/4 · 4/4
```

T4 stays 3/4 because its gold is ambiguous (two real definitions), not because
of language. A hint also lifts the `ask_rewrite` gate: the host has named the
subject, so the server can answer exactly.

**Consequence for the plan:** the "RU→EN code lexicon" and "concept→symbol
dictionary" items are dropped. The queue keeps only language-agnostic work:
fusion ranking, measurement hygiene, and the hints contract as the bridge.

## What this changes

The RU→EN lexicon is **not justified as a language fix**: English prose is as
blind as Russian prose (1/4 vs 0/4). The gap is **prose → identifier**, in any
language: "the decision to reindex a file" does not name `FreshnessChecker`,
and neither does the Russian version. A Russian-only dictionary would close at
most one of four tasks and would leave the English prose gap untouched.

T4 is not a counter-example to `name`: `get_call_chain` has **two real
definitions** (`PureGraphMixin.get_call_chain` in `graph_adapter_pure.py` and
`SymbolIndex.get_call_chain` in `symbol_index.py`). The top-1 row is a
declaration the gate verified; the gold column picked one of the two. The
lesson is about the gold, not the ranking: name tasks with several definitions
belong in an ambiguity bucket (`all golds required`), as XERJ already does for
A01-A04.

The queue item "RU→EN lexicon for the symbol channel" is therefore replaced by
"prose → symbol bridge (language-agnostic)": name variants from the question's
content words (already partially present in the `names` channel) plus a small
code-domain synonym map, with the same bar (top-1 ≥ 7/16, negative 4/4, `any`
not lower). T4 also shows a separate ranking gap on an exact identifier —
`get_call_chain` is found but not first — which the fusion A/B (E-next) covers.

## Limits

- 4 base tasks: one task is 25% of this panel. The claim is directional.
- The `en` formulations are written by the same author as the `ru` ones, so
  they share the same assumptions about what a prose question looks like.
- Gold is file-level, and T4's gold was ambiguous (two real definitions), so the
  `name` row in the table understates it.
