# Commit-localization benchmark — frozen plan (before the first run)

Date: 2026-11-10. Design rationale: `experiments/bench_2026_11/DESIGN.md`.
Owner objection this answers: *"we wrote the test and tuned to it"*.

## Source (nobody authors it for us)

- **Corpus commit** `B = 7c2c7a3c6417539bc08f807d6790fe6e722d3a84` (2026-09-06,
  `HEAD~150` on this tree). One index is built at `B` and never at `HEAD`.
- **Tasks**: commits in `(B, HEAD]` — the fixes are *not* in the corpus, so a
  search cannot find the answer by reading the fixed code.
- **Query** = the commit message (subject + body), verbatim. Typos, "wip",
  Russian/English mix — all kept. We do not rewrite questions.
- **Gold** = the files that commit changed, by one rule applied to every commit
  before any result is seen:
  - merge commits: excluded;
  - commits changing 0 or > 20 files: excluded;
  - commits whose changed files are all outside `src/`, `tests/`, `scripts/`,
    `tools/`: excluded (docs-only and experiment-only churn is not this task);
  - `CHANGELOG.md`, `*.lock`, `requirements*.txt`, `pyproject.toml`,
    `experiments/**`: never gold;
  - remaining commits: gold = their changed code files.

## Split

Sorted by commit date: first 70% = **dev**, last 30% = **sealed**. The sealed
list and gold are hashed into `MANIFEST.sha256` and committed before the first
sealed run. The runner prints sealed numbers only with `--sealed`, used once per
release.

## Metrics (computed, never typed)

- file-level `hit@1`, `hit@5`, `any@8`, `MRR`;
- per task first, rates with Wilson 95% after;
- paired delta tool − grep on the same tasks (McNemar-style counts, printed).

## Baselines in the same table

- `grep`: every file whose source contains a content word from the message,
  ranked by number of distinct matched terms, path order as the tie-break.
- The tool: `investigate` on the message, limit 8.

If the tool does not beat grep, the report says so.

## Amendment 1 — a fair baseline (recorded before the first tool run)

While building the harness, the grep control scored 1/10 `hit@5` on the first ten
dev tasks. That is too weak to be an honest baseline: a weak baseline flatters
the tool, and this whole benchmark exists to avoid that.

So a third arm is added, frozen here and computed from the same corpus:

- `search`: the product's own search channel used **alone** —
  `hybrid_search_async(query, limit=50, rerank=False)`, files from
  `metadata.file`, order preserved, no merge, no graph, no evidence gate.

`grep` stays as a floor, `search` becomes the baseline that matters: it is "what
this codebase does with a message and nothing else". P2 is read against
`search`.

## Amendment 2 — unsolvable tasks (before the full measurement)

The corpus at `B` does not contain files created after `B`. Measured on the
frozen panel: **66 of 174 tasks** (50 of 121 dev, 16 of 53 sealed) have **no**
gold file in the corpus. No tool can find a file that does not exist, and
counting those as misses understates every arm — and invites "fixing" it by
tuning.

Rule, applied to every task before the numbers:

- a task is **kept** if at least one of its gold files exists at `B`;
- a hit is any *kept* gold file in the top-k (so a task with a 3-file gold where
  1 file exists is still fair);
- dropped tasks are counted and printed with every rate, and the full panel
  (including them) is reported in a second column.

The 5-task smoke that ran before this rule was a harness check, not a
measurement; its numbers are discarded.

## Amendment 3 — the `neighbours` arm (before the sealed run)

Dev showed that 36 of 52 misses are `abstain` with **zero rows**: the gate
extracts identifiers from the message, they do not occur in the corpus (they are
names the commit introduces), and the tool withholds its neighbours. Re-running
those 52 tasks with `include_neighbours=true` recovered **18 at hit@5** and 25 at
any@8.

So a fourth arm is frozen here, before the sealed run:

- `neighbours` = the same tool with `include_neighbours=true`.

Dev is re-run with all four arms so the table is consistent, and the sealed split
is run **once** with all four. The arm is a product variant, not a tuning of the
metric: it changes what the caller asks for, not how the score is computed.



## Predictions (frozen)

| # | Prediction | Falsifier |
|---|---|---|
| P1 | dev `hit@5` >= 0.35 | below 0.35 |
| P2 | tool `hit@5` >= grep `hit@5` + 5 tasks | gain < 5 |
| P3 | `any@8` >= `hit@5` on every bucket (by construction) | violated |
| P4 | sealed `hit@5` within +/- 0.10 of dev | outside the band |

P4 is checkable only at the sealed run; it is the overfit alarm.

## Guards

- **Corpus pin**: the runner records `build_head` from the graph meta and refuses
  to run if it is not `B`.
- **Leak check**: no task's gold file may be modified between `B` and the task's
  own commit *before* that commit — that is what `B` being the parent guarantees
  for the first commit of each file; later tasks may share files, and that is
  reported as a known property, not hidden.
- **Determinism**: 10 tasks re-run 3 times; any change in `top1` is printed.
- **No silent denominator**: a task that fails to run aborts the report.

## What this does not cover

- Docs questions, ambiguity, prose-only retrieval: separate panels.
- The corpus at `B` is one snapshot; a file renamed after `B` makes its task
  unsolvable by construction. Such tasks are counted as misses and reported with
  the rename as the reason, not silently dropped.
- We can still look at the sealed set after the run. The only real defense is
  time plus external repos (`DESIGN.md`, B2).
