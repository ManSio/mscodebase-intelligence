# ORDER_RULE — the expectation, fixed before the run

**Frozen:** 2026-10-06, before any run. Written because the author's own note corrected us: ordering
applies **only among notes that match the same act and share a rotation tier**. Comparing across tiers
would look like an ordering failure while the rotation rule is simply doing its job.

## The rule we will score against

Let `C` be the candidate list for one act, after matching and after eligibility (session cap, backoff,
staleness, holdback). Partition `C` into tiers by the ledger keys `act-session:<session>:<act>:<name>`
and `act:<act>:<name>` — i.e. "times this crystal already spoke this session for this act" and "when it
last fired for this act".

1. **Tiering is decided before overlap.** Inside a tier, higher overlap first.
2. Within a tier with a **clear** overlap gap (Jaccard difference ≥ 0.10, fixed now), `CRYSTAL_ORDER=overlap`
   and `CRYSTAL_ORDER=rotation` **must** produce different orders. If they do not, H3/H5 are untestable.
3. Across tiers, `overlap` and `rotation` **must not** change the order.
4. With a single candidate, order is trivially stable.
5. `overlap(ctx, essence)` = Jaccard over lowercase `\w{3,}` token sets, essence truncated to its first
   1500 characters. Tokens shorter than three characters and non-word characters do not count.
6. The winner is exempt from the half-budget cap; everything behind it is capped at
   `max(320, budget/2)` where `budget = 4000` characters. A delivered crystal carrying the head marker
   `…[head only` counts as **headed, not delivered-in-full**, and the two must be reported separately —
   a metric that improves because the hard case stopped being counted is the defect this repo keeps
   finding in its own instruments.

## What we will NOT score

- **Not** whether the ordering is *good* for a reader. That needs behaviour, not a key.
- **Not** whether the budget of 4000 characters is the right number.
- **Not** precision of act-matched notes in general. Our own repo is the foreign corpus for that, and it
  is a separate experiment with its own frozen input.
- **Not** the `SPEC_THRESHOLD = 8` value itself, only whether the author's own caveat about it stands.

## Reporting contract

For every act we report: candidate count, candidate names in delivered order, tier of each, overlap
score of each, delivered/headed/starved split, and the same list under `CRYSTAL_ORDER=rotation`.
Averages over acts are reported **with the denominator printed**, because a rate on an empty set is not
a result: if an arm yields zero candidates for every act, the run reports `population empty` and exits
non-zero instead of printing a clean sheet.
