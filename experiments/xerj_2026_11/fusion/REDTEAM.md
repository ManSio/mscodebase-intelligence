# Fusion A/B — Red Team (before reading the result)

Attacks against the *measurement*, not the product. Each one: how it would make
us report a wrong winner, and what closes it.

| # | Attack | How it corrupts the result | Defence |
|---|---|---|---|
| R1 | **Order bias** — the first arm of each task runs on a cold cache, and its rows are the ones pass 2 reuses | one arm systematically slower/worse | arms rotate per `(task + run) % 3`; every arm is first, second and third equally often |
| R2 | **RRF kills the definition policy** — in a reference question the definition must not lead, but a hand-tuned cap (0.5) is absurd on ranks of ~0.017 | "who calls X" regressions, invisible in top-1 rates | cap is per-scale: `weights 0.5`, `norm 0.0`, `rrf 0.0`; test `test_definition_demotion_survives_every_arm` runs all three |
| R3 | **Concurrent channels** — `asyncio.gather` interleaves appends, so a naive index-by-position would give a channel's second hit another channel's rank | non-deterministic arm, flaky numbers | counters are per channel (`seen_in_channel`), test `test_rrf_keeps_per_channel_ranks_under_interleaved_arrival`; the run prints a `flaky` column |
| R4 | **A test that cannot fall** — the first version asserted only "which file is first" and stayed green when the RRF formula was replaced by `score + weight` | false confidence in the whole A/B | tests now assert rank values (1/60, 1/61, 2.5, 0.56); mutation turns 4 red (LEDGER row 2) |
| R5 | **Double counting one channel** — the same channel can hit one row twice (two items, same file+line) | RRF treats one ranking as two votes | guard `channel not in votes[key]` (one vote per channel per row); test `test_rrf_counts_a_channel_once_per_row` |
| R6 | **Tie-break hides the formula** — the sort key is `(rank, len(channels))`, so consensus can win on the tie-break rather than the score | an arm "wins" for a reason we did not measure | the same tie-break runs in every arm, and per-task diffs are printed; a tie that flips shows up as `changed` |
| R7 | **Pass-2 coupling** — `first_pass` (top 50, then top-3 files) feeds the impact/tests channels, so a formula that reorders the first pass changes *which channels fire at all* | arms differ by more than ordering | named, not hidden: this is inherent to a two-pass tool. The A/B measures the net effect, which is what ships. It also means an RRF win cannot be explained by ranking alone — the report must say so |

Kill condition stays as frozen: any loss of `any` on a positive panel, or a row
appearing on a negative, keeps the shipped arm regardless of the top-1 gain.

## Review round 1 — findings and what changed

An independent reviewer with fresh context (only the diff, the acceptance
criteria and a checklist) found two blockers and five majors. The first A/B run
was **stopped** and its partial data discarded: measuring a build with a known
policy bug would have produced an unfalsifiable number.

| # | Finding | Fix |
|---|---|---|
| R8 | **Blocker:** the `norm` demotion cap (0.25) sat above a `references`-profile neighbour (0.12), so the definition led again in that arm | cap is `weights 0.5`, `norm 0.0`, `rrf 0.0` — the policy is "tail", not a number; regression test with the profile's real weights |
| R9 | **Blocker:** in `rrf` every channel's first hit is exactly `1/60`, and the tie-break was arrival order — channels append concurrently, so RRF top-1 was not reproducible | stable sort with a path tie-break `(rank, len(channels))` over `(file, line)` order; test that swapping arrival does not swap output |
| R10 | **Major:** bucket penalty is an absolute `-1.5/-2.0`, i.e. a hard ban on the `rrf` scale (~0.017) | penalty is scaled per arm (`weights 1.0x`, `norm 0.4x`, `rrf` -> tail) |
| R11 | **Major:** `_MAX_WEIGHT = 2.5` was not the real maximum (`name` uses 3.0), so `norm` silently halved that channel | `_MAX_WEIGHT = 3.0` |
| R12 | **Major, and the fix was wrong:** I merged `definition` and `symbol` into one family on the theory that they are one lookup. They are two different searches (`find_definitions` vs `search_symbols`), so the merge shifted the arm against the frozen formula | round 2 caught it; families removed, each channel has its own counter, a row found by both gets 2/60 |
| R13 | **Major:** old tests encoded the shipped formula without pinning the switch, so a shell with `MSCODEBASE_FUSION=rrf` failed them | autouse fixture in `tests/conftest.py` clears the variable; arm tests set it themselves |
| R14 | **Major/nit:** one test asserted arrival order for equal ranks, not the penalty policy | assertion now checks equal ranks (the policy) instead of which file came first |
| R15 | **Nit:** `results.json` was written on `--limit` smoke runs | the runner refuses to overwrite results on a smoke run |

Accepted without a fix, and stated in the report: RRF ignores the channel
`score`, so the `raise`-statement bonus and the search channel's own rank curve
do not act in that arm. That is what pure RRF is; it is a difference between the
arms, not a bug in one of them.

## Review round 2 — attacks on the harness itself

The first attempt at the A/B was stopped **twice**: once for the policy bugs
above, once for these. Both were caught before a number was published.

| # | Attack | What it would have produced | Defence |
|---|---|---|---|
| R16 | **Re-implemented scoring**: the runner's own `_score` did `path.endswith(str(gold))`, but the panel's gold is a **list** (and an ambiguity task needs *all* golds) | every XERJ task scored `False` in all three arms: a clean-looking table of zeros, and "no difference between arms" | deleted the copy; the runner calls `run_baseline.score`, the same function the gate uses. Smoke went from 0/3 to 2/3 top-1 on P01-P03, which is how the leak was confirmed |
| R17 | **Shrunken denominator**: `per_task` drops invalid runs, so a channel timeout silently removes a task from the panel | rates computed over 51 of 53 tasks read higher, and nothing says so | guards count invalid runs and scored tasks per arm; any invalid run or a panel mismatch aborts with exit 3 |
| R18 | **No-op switch**: if `MSCODEBASE_FUSION` never reaches `_merge`, all three arms measure the shipped formula | a perfect tie, reported as "weights already optimal" | `_run` asserts `_fusion_mode() == arm`; the runner also aborts if every arm returned identical rows for every task (exit 4) |
| R19 | **Stable metric, unstable arm**: `top1` can agree across repeats while the returned rows differ | "deterministic" claim that only covers the boolean | `_determinism()` compares the file list per task across repeats; the count is printed per arm |

Still open, and named rather than fixed:

- **Shared warm state** — one `InvestigateTool` per root serves all arms, so the
  first call of the session is colder than the rest. Rotation (R1) spreads that
  across arms, but it is not removed.
- **Author bias in the metamorphic panel** — its 12 asks were written by the
  same author as the hypotheses; they are a control, not an independent sample.
- **Post-hoc selection** — five frozen criteria are reported; no "best bucket"
  is picked after the fact. If a bucket is quoted, it is quoted with its
  denominator and Wilson interval.


