# Scale panel — red team (after the first run)

Attacks on the E66 result. Two of them are uncomfortable, and both change what
the number may be used for.

## A1. Triviality: does plain grep solve this panel?

Control: for each positive task, find every `.py` file whose source literally
defines the symbol (`^\s*(async def|def|class) <name>\b`) and take the first hit
in path order. No index, no ranking.

```
bucket       grep top1   tool top1   grep any   tool any
name         147/160     154/160     160/160    157/160
qualified     23/40       38/40       33/40      40/40
```

**Verdict: the `name` bucket is a grep test.** A one-line `grep` with no
retrieval at all reaches 91.9% top-1 and 100% recall, against the tool's 96.3%
and 98.1%. The difference is real but small, and the tool *loses recall*: three
tasks that grep finds are missed entirely.

`qualified` is the opposite: grep 57.5% vs tool 95%, so that bucket does
discriminate. Twelve points of the headline rate come from 40 tasks, not 160.

**Consequence:** the 0.963 `name` rate must not be published as search quality.
It is a regression detector, as the frozen plan said — but now with a number
behind the caveat.

## A2. A real bug the panel found: `test_impact.py` is treated as a test file

The three `any` misses (tasks 1, 43, 127) are all definitions in
`src/core/test_impact.py` — `risk_level:178`, `module_of:55`,
`referenced_modules:63`. The tool returns `abstain` or never lists the file,
while grep finds it at line level.

Cause: `_bucket_penalty` classifies by path, and `_TEST_PATH_RE` matches any
`test_*.py`, including a production module named for *test impact prediction*:

```
_bucket_penalty('src/core/test_impact.py', 'where is risk_level defined') -> -2.0
_bucket_penalty('tests/test_x.py',        'where is X defined')            -> -2.0
_bucket_penalty('src/core/artifact_paths.py', ...)                         ->  0.0
```

Blast radius, measured: 926 tracked `.py` files; 271 match the regex; 260 of
them also contain `def test_` or import a test framework (real tests); **1
production module is misclassified** (`src/core/test_impact.py`). The other
matches are under `experiments/` and `scripts/`, which the panel does not sample.

This is the most valuable output of the run: a defect the 41-task panel never
touched, because none of its questions pointed at that file.

## A3. Selection bias: who is in the panel

```
graph definitions                 5958 symbols
with exactly one definition       5809
after code-only filter            2584
matching the `name` regex          791   -> 160 sampled (20%)
matching `qualified` regex        1483   ->  40 sampled (3%)
dropped by regex (short/dunder)    310
```

The panel samples distinctive names only: 5-40 characters, no dunders, no
one-letter helpers. That is a defensible choice (a question about `x` is not a
question), but it makes the panel easier than the corpus, and the rate inherits
that.

## A4. Determinism: one run is not enough

24 positive tasks x 3 repeats: `unstable_metric=0`, `unstable_top3_rows=0`.
But task 197 (`MultiProjectSearcher.cross_repo_search`) scored `top1=False` in
the original run and `top1=True` in all three repeats afterwards, with the same
code and the same panel. So the per-task result can move *between sessions*
(index freshness), even though it is stable within one.

**Consequence:** a single-run rate is a point with unmeasured session noise.
Every published number from this panel must be a 3-repeat majority, as in E65.

## A5. Leakage the panel cannot see

Gold comes from the index, so by construction the gold file is indexed. The panel
therefore cannot detect indexing gaps (a file the indexer skipped is never a
gold). It measures ranking and name resolution, not coverage.

## What changes because of this

1. E66 stays as **instrument calibration** (the anchors reproduced E65 exactly),
   not as a quality claim, and `REPORT.md` now says so with the grep control in
   the same table.
2. The `test_impact.py` misclassification becomes its own frozen experiment
   (E67), not a silent edit: bar is `any@8` +3 on this panel with no loss on the
   anchors, 3 repeats.
3. Published rates from this panel require 3 repeats and the grep control next
   to them.
