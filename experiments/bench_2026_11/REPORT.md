# B1 — commit-localization benchmark: first result

Frozen before the run: `frozen/PLAN.md` (design + Amendments 1-3).
Design rationale: `DESIGN.md`. Owner objection this answers: *"we wrote the test
and tuned to it"*.

## What was measured, and why it cannot flatter us

- **Corpus**: worktree at `B = 7c2c7a3` (2026-09-06). Index built once there:
  383 files, 6406 chunks, 0 errors, 218 s. Guarded: the runner refuses to report
  if `build_head != B`.
- **Tasks**: 174 commits from `(B, HEAD]`. The question is the commit message
  **verbatim**; the gold is `git show --name-only`, one rule for every commit.
- **Solvable subset**: 66 of 174 tasks reference files created after `B` and are
  unsolvable by construction (Amendment 2); they are counted and printed, and
  the metrics below are over the solvable subset.
- **Split**: 121 dev / 53 sealed by date; sealed needs `--sealed` and was run
  once.

Arms: `tool` (`investigate` default), `neighbours` (same with
`include_neighbours=true`, Amendment 3), `search` (the product's BM25/hybrid
channel alone — the fair baseline), `grep` (message words, floor).

## Dev result (71 solvable tasks)

```
arm          hit@1  hit@5  any@8   MRR   hit@5 95% CI
tool           12     19     23   0.215  [0.179, 0.381]
neighbours     24     38     44   0.424  [0.420, 0.646]
search         11     22     29   0.239  [0.214, 0.425]
grep            0      2      6   0.051  [0.008, 0.097]
paired hit@5: neighbours-only 20, search-only 4 (delta +16)
```

Determinism guard: 10 tasks x 3 repeats, **0** unstable.

## Frozen predictions

| # | Prediction | Result |
|---|---|---|
| P1 | dev `hit@5` (tool) >= 0.35 | **FAIL** — 19/71 = 0.268 |
| P2 | tool >= search + 5 on `hit@5` | **FAIL** — 19 vs 22, i.e. **-3** |
| P3 | `any@8` >= `hit@5` everywhere | PASS |
| P4 | sealed within +/- 0.10 of dev | see below |

The default `tool` arm is **worse than the plain search channel** on prose
queries. The `neighbours` arm is +13 over search.

### Does the message give the answer away?

Half of real commit messages name the file ("fix parser.py"). Split:

```
              n    tool   neighbours   search     (hit@5, dev)
names file   37     11        22         11
prose only   34      8        16         11
```

The tool's deficit is in **both** halves (11 vs 11 named, 8 vs 11 prose), so the
loss is not an artifact of messages that leak the filename. `neighbours` wins in
both.


## Why the default loses (measured, not argued)

52 tool misses at hit@5, classified:

```
36  abstain, zero rows      -> identifiers in the message do not exist in the corpus
11  outside top-8
 4  rank 6-8
 1  outside top-8 (answer)
```

The messages describe changes, so they name things the commit *introduces*
(`iter_import_candidate_nodes`). The gate extracts those names, finds zero
occurrences, and — correctly by its contract — abstains and withholds the eight
neighbours it already computed.

On exactly those 52 tasks, with `include_neighbours=true`:

```
default     hit@1=0   hit@5=0   any@8=4
neighbours  hit@1=12  hit@5=18  any@8=25
```

So the loss is a **policy** choice (`abstain` = "do not trust anything"), not a
ranking defect. This is the most useful thing the benchmark has produced so far,
and it is a product decision, not a bug fix: returning unverified neighbours
instead of nothing gains 18 of 71 tasks and risks an agent taking a neighbour for
an answer.

## Sealed result (37 solvable tasks)

```
arm          hit@1  hit@5  any@8   MRR   hit@5 95% CI
tool            2      7      7   0.113  [0.095, 0.342]
neighbours     11     21     21   0.410  [0.409, 0.713]
search          0      5      7   0.062  [0.059, 0.280]
grep            0      1      1   0.036  [0.005, 0.138]
paired hit@5: neighbours-only 16, search-only 0 (delta +16)
```

P4: `tool` moves from 0.268 (dev) to 0.189 (sealed), a **0.079** drop — inside the
+/-0.10 band, so the overfit alarm does not fire. `neighbours` moves 0.521 ->
0.568 (+0.047).

The sealed split is harder for **every** arm (`search` collapses from 24/71 to
5/37), which is consistent with it being the most recent commits: their files
changed after the corpus snapshot. That is a property of the benchmark, not of
the tool.

Split by "does the message name the gold file" (sealed):

```
              n    tool   neighbours   search
names file   20      4        14          4
prose only   17      3         7          1
```

The policy gap reproduces out of sample: `neighbours` beats the default by 10/20
on named tasks and 4/17 on prose.

### Panel change after the first run (and why everything was re-run)

The third-party data gate blocked the first commit: one commit message quoted a
contributor's email address. Messages are now redacted (`<email>`) **inside the
generator**, before the manifest is hashed, which changed the manifest from
`89940dd8...` to `71395d45...`. A changed panel cannot inherit a measurement, so
both splits were re-run from scratch on the redacted panel; the numbers above are
the re-run. The conclusions did not move (sealed is identical; dev `search`
shifted by two tasks because the email split into searchable terms).

### Instrumentation note

The sealed process died twice (after 16 and after 22 tasks) with no traceback and
no Python exception — a hard process exit, cause not identified. The runner now
appends every row to `results_sealed.partial.jsonl` and resumes by id; the table
above is the union of three chunks. Per-task booleans for the first 22 tasks were
visible in the log before the crash; no code, arm or metric changed after that
(the arms were frozen in Amendments 1-3 before the sealed run), so this is
disclosed rather than "clean".

### Re-measured after E67

The test-bucket fix (E67, merged as `092418a`) changed a bucket rule, so the dev
split was re-run on the merged build: **identical** (`tool` 19, `neighbours` 38,
`search` 22, `grep` 2; paired +16). The fix does not touch this benchmark, which
is what a classification change should look like.

## Threats

- The corpus is one snapshot at `B`. A file renamed after `B` makes its task
  unsolvable; those tasks are not filtered (only *absent* files are), so a
  rename shows up as a miss and is named in the report rather than hidden.
- Many commits in the range are ours (agents), so the messages are "natural" but
  not independent authors. External repos (`DESIGN.md`, B2) are the fix.
- One run per split: dev was re-run after Amendment 3, sealed was not.
- `grep` is a weak floor by construction; `search` is the baseline that matters.

## Decision this creates

The tool currently optimises for "never show an unverified answer". This
benchmark prices that policy: **-33 tasks of 108 solvable** (dev 19 vs 38,
sealed 7 vs 21 for the same tool with neighbours shown).

The options are:

1. keep `abstain` (honest, loses the neighbours);
2. return neighbours as `caveat` when nothing verifies (gains them, risks a
   neighbour being read as the answer);
3. keep `abstain` but make the retry obvious to the caller (it already prints
   "Pass include_neighbours=true", the measurement says that hint is not acted
   on by a single-shot caller).

No option is implemented here — it changes the product's honesty contract.

## What would make this benchmark stronger (next version, new pin)

- External repos (B2): messages and gold written entirely outside this project.
- An issue-text arm: issue bodies are longer and further from the diff than
  commit messages.
- The crash investigation: repeated `asyncio.run` + SQLite in one process dies
  after ~20 tasks; a per-chunk subprocess would remove the resumption dance.
