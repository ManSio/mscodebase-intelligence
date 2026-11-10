# Scale panel — result (E66)

Frozen before the run: `frozen/PLAN.md`. Panel generated from commit
`e81e0b0` (`sha256(commit)` seed), 281 tasks, one arm (shipped defaults).

## Result

```
bucket                    n   top1    any   chars/top1   95% CI top1
name                    160    154    157        2163    [0.92, 0.98]
qualified                40     38     40        2669    [0.83, 0.99]
negative                 40     40     40         332    [0.91, 1.00]
anchor:xerj/positive     16      6     10        5894    [0.18, 0.61]
anchor:xerj/ambiguity     4      0      2         n/a    [0.00, 0.49]
anchor:xerj/negative      4      4      4         359    [0.51, 1.00]
anchor:mcp_audit/pos     17     11     14        3442    [0.41, 0.83]
                                             invalid runs: 0
```

`chars/top1` is answer characters divided by the number of top-1 hits — an
estimate of answer cost per correct answer, **not** a tokenizer measurement.

## Frozen predictions

| # | Prediction | Result |
|---|---|---|
| S1 | generated `name` top-1 >= 0.60 | **PASS** — 154/160 = 0.963 |
| S2 | negatives yield no rows on >= 0.95 | **PASS** — 40/40 |
| S3 | anchors reproduce E65 `weights` within +/- 2 | **PASS, exactly** — xerj 6/16 and mcp_audit 11/17, the same two numbers |
| S4 | `qualified` top-1 <= `name` top-1 | **PASS** — 0.950 <= 0.963 |

## What this does and does not mean

**It means the instrument is calibrated.** The anchors did not merely stay within
two tasks — they reproduced E65 exactly (6/16, 11/17). Two independent
experiments, two different runners, same panel: the measurement is stable enough
to compare against.

**It does not mean "search is 96% accurate".** The generated questions contain
the identifier, and the grep control below shows it: a plain `grep` reaches
91.9% on the same `name` tasks. The number is a **regression detector**, not a
quality claim — it says "exact names resolve, 154 of 160 times", and nothing
about prose questions (`hints`, E64), ambiguous golds (XERJ A01-A04) or docs
routing.

The cost column shows the same thing from another side: a generated task costs
2163 chars per correct answer, an XERJ prose task 5894. The difference is task
difficulty, not an improvement in the tool.

## Controls (red team, `REDTEAM.md`)

**grep baseline** — every `.py` file that literally defines the symbol, first
hit in path order:

```
bucket       grep top1   tool top1   grep any   tool any
name         147/160     154/160     160/160    157/160
qualified     23/40       38/40       33/40      40/40
```

So the `name` bucket is close to a grep test (91.9% vs 96.3%), while `qualified`
discriminates strongly (57.5% vs 95%). Read the headline rate with that in mind.

**Selection bias** — 5958 graph symbols -> 5809 unique -> 2584 code-only ->
791 eligible `name` names -> 160 sampled (20%). The panel uses distinctive names
(5-40 chars, no dunders), which makes it easier than the corpus.

**Determinism** — 24 tasks x 3 repeats: metric stable. But one task
(`MultiProjectSearcher.cross_repo_search`) differed between the original run and
later repeats, so a single-run rate carries session noise: published numbers
from this panel need 3 repeats, as in E65.

## The 6 misses, honestly

Three of the six are one bug, not three retrieval misses: `risk_level`,
`module_of` and `referenced_modules` all live in `src/core/test_impact.py`, and
the bucket classifier penalises that production module by `-2.0` because its
name starts with `test_`. Measured blast radius: 926 `.py` files, 271 match the
test regex, 1 production module is misclassified. That is E67, with its own
frozen bar.

The remaining three are ranking (`expect`, `CommitMemory.get_hotspots` found at
row 2) and name resolution. The generator records ids, so the list is
reproducible from the same commit.


## Instrument findings (found while building the panel, not fixed here)

1. **Foreign graph nodes.** `graph.find_nodes()` returned a node whose file
   (`src/sources/manifest/extract.py`) does not exist in this project. The
   generator now requires the file to exist; the tool still enumerates such
   nodes.
2. **Phantom `Function` nodes for calls.** `callable` in
   `src/core/di_container.py:160` is `if callable(close_method):`, but the graph
   labels it `Function`. The evidence gate is **not** fooled — `investigate`
   returns that row without `✓def` and the verdict is `caveat (0.40) — no
   verified declaration` — but the symbol channel still ranks a non-definition.
   Follow-up: parser filter plus a regression test.

Both would have silently depressed the generated rate (a task whose gold does
not define the symbol can never be answered), which is why the generator now
verifies gold at build time: `phantom_gold = 0` on the shipped panel.

## Reproduce

```
python experiments/scale_2026_11/generate.py     # same commit -> same 281 tasks
python experiments/scale_2026_11/run_scale.py    # ~15 min, 3 s per task
python experiments/xerj_2026_11/wilson.py        # intervals
```
