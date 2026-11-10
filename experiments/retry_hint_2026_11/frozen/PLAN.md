# Retry hint — frozen plan (option C, before the code change)

Date: 2026-11-10. Owner decision: **C** — keep `abstain` (never present an
unverified row as an answer), but make the continuation explicit instead of
leaving it in prose that a single-shot caller does not act on.

Measured before this change (E68): 36 of 52 default misses on the commit
benchmark are `abstain` with zero rows, and the neighbours that were withheld
carry 19 of 71 hit@5 (dev) and 14 of 37 (sealed).

## Change

When the gate withholds rows, the answer ends with a machine-readable block:

```
Neighbours withheld: 8 (unverified).
next: investigate(query="...", include_neighbours=true, limit=8)
```

`ask_rewrite` gets the same shape (`next: investigate(query="...", hints=[...])`)
so a caller never has to parse prose. No row is added to the default answer; the
verdict stays `abstain`.

## Predictions (frozen)

| # | Prediction | Falsifier |
|---|---|---|
| R1 | B1 dev `hit@5` of the **default** arm stays 19/71 | any change (rows leaked) |
| R2 | every answer with withheld rows carries a `next:` line that names `include_neighbours=true` | any withheld answer without it |
| R3 | following the hint reaches `hit@5` >= 36/71 (the neighbours arm measured 38) | below 36 |
| R4 | `ask_rewrite` answers carry a `next:` line with a `hints=[...]` placeholder | any without it |

R1 is the honesty check: C is supposed to change the text, not the evidence.

## Measurement

`experiments/retry_hint_2026_11/agent_loop.py` on the B1 dev split:

1. call `investigate` with defaults, record `top1`/`hit@5` and whether a `next:`
   line with `include_neighbours=true` is present;
2. if present, replay with `include_neighbours=true` and score again;
3. report default, after-hint, and the count of emitted/absent hints.

No new panel: the tasks, corpus (`B = 7c2c7a3`) and gold are E68's, unchanged.
