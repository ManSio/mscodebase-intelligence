# Benchmark design — a test we cannot tune to

Date: 2026-11-10. Problem statement (owner): every panel so far was authored by
us, so "we tuned it ourselves" is a fair objection. This is the design that
removes the author from the loop.

## The three ways a benchmark can be gamed, and the fix for each

| Hole | How we exploited it (E66) | Fix |
|---|---|---|
| **We write the questions** | generated `name` tasks contain the identifier; grep solves 91.9% | take the query from **real text we did not write** (commit messages, issue bodies) |
| **We pick the gold** | gold = symbol definition, chosen by the generator's filters | gold is **computed by a rule** from git (`git show --name-only`), no human choice |
| **We can look and retune** | full panel visible while iterating | **temporal split + sealed eval**: tuning set and eval set are different commits, eval runs once and its hash is committed first |

## B1 — commit localization (the main benchmark)

For every non-merge commit `C` in a pinned range:

- **query** = the commit message (subject + body), with the diff removed. The
  text is written by whoever fixed the bug — not by us.
- **gold** = the set of files changed in `C`, minus merge commits, minus commits
  touching more than 20 files, minus commits whose message is a changelog/typo
  stub. The filter is one rule, applied to all commits, before any result is
  seen.
- **corpus** = the repository at commit `B`, where `B` is *older* than every task
  commit. One index build serves the whole task set, and the fix is not in the
  corpus. This is the leak that makes naive "ask about HEAD" benchmarks
  worthless: the fixed code is right there in the index.
- **metric** = file-level hit@1 / hit@5 / any@8 and MRR. Exact, no judge, no
  rubric. Per task first, rates with Wilson intervals second.

Why this resists tuning: the questions are the developers' own sentences
(including typos, "wip", "fix"), the gold is what git says changed, and the
corpus predates the fix. We do not get to pick a flattering subset without
saying so in the rule.

### Split

- Sort tasks by commit date.
- First 70% = **dev set** (visible, tuning allowed).
- Last 30% = **sealed set**. Its task list and gold are hashed and committed
  *before* the first sealed run. The runner refuses to print per-task sealed
  results unless `--sealed` is passed, and that flag is used once per release.
- Report dev and sealed separately. A change that helps dev and not sealed is
  reported as such.

### Baselines that must be printed next to us

- `git grep` on the message's identifiers (the E66 control, measured: it wins on
  easy tasks).
- BM25 over the same corpus with no graph, no symbols, no gate.

If we do not beat both, the benchmark says so — that is the point.

## B2 — external repositories (the strongest check)

The same generator over 2-3 pinned external repos where we have never written a
line: the commit messages and the gold are entirely independent of us. Repos and
commits are pinned in a `frozen/PINS.md` with the sha, and the runner verifies
the sha before running.

This is the only version where "they tuned to it" is impossible by construction;
its cost is cloning and indexing a few external trees.

## B3 — definition lookup (what E66 was)

Keep it, but label it **regression detector**, never a quality number: a plain
grep already reaches 91.9%, measured.

## Determinism, the part the owner asked about explicitly

"Same exact evaluation" means: same code + same commit + same task set + same
index state -> same numbers. Two things make that hard here:

1. **Index freshness.** E66's task 197 differed between sessions while being
   stable within a session. Fix: the runner builds the index once into a
   dedicated data dir, records its `build_head` and file count, and refuses to
   report if the index changed mid-run.
2. **Concurrency.** Channels run in parallel; equal scores are ordered by the
   deterministic tie-break we added in E65, so repeated runs agree (measured
   24 tasks x 3 runs, 0 drift).

Any published number must come from `bench/run.py` — not from a hand-written
table. The metric lives in code, the task set lives in a hashed file.

## What this cannot fix

- **We can still see the sealed set** and re-tune afterwards. The only real
  defenses are the temporal split (future commits are unseen by construction)
  and external repos (B2).
- **A benchmark is a sample.** n and intervals decide whether a delta is real;
  the rule "one task is one task" (paired counts, not rates) stays.
- **Corpus drift**: the repo changes, so old tasks may become trivial (the fix
  file gets renamed). Re-pinning the range is a new version of the benchmark;
  versions are never edited in place.

## Order of work

1. `bench/commit_tasks.py` — build tasks from git, one rule, hashed manifest.
2. `bench/run.py` — index at `B`, run tasks, exact metrics, paired deltas.
3. `bench/baseline.py` — grep and BM25 rows in the same table.
4. Sealed split + manifest hash committed before the first sealed run.
5. B2 on one external repo, then a second.
