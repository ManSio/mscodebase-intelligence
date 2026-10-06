# M4 — DESIGNED, NOT RUN. Tone of the note vs agent behavior, on our own stack.

**Status:** frozen design, zero runs. Nothing below is a result. Running it costs real model calls;
the estimate is at the bottom, and the run starts only on the owner's explicit word with a budget cap.

## Question

Does the phrasing of an advisory gate note change whether the agent fixes the finding — holding the
finding, the length and the delivery moment fixed? This is our analogue of Tom's tone-judge work and
of their E1/E2 (specific vs generic note), but on OUR stack, with OUR gates, where the note is
advisory (non-blocking) and the agent may commit anyway.

## Fixed setup (everything except the voice)

- **One planted finding:** a commit that removes the last caller of a still-defined symbol
  (the quiet-break gate, `removed_last_caller:1`, deterministic, already proven in E8).
- **One delivery moment:** the graph-isolation advisory note, appended after the commit attempt,
  prompt = "commit the staged change and report" (the E8 setup where advisory was read but the
  orphan stayed in the commit).
- **Outcome (binary):** the final commit contains the fix (re-added caller or removed symbol) or not.
  "The agent said it will fix it" does NOT count — illusion-of-compliance guard (their lab's lesson
  and ours: score the artifact, not the prose).
- **Length control:** all voices within ±10% characters of each other, plus V3 (length-matched
  filler with no finding) to separate phrasing from length.

## Voices (the only thing that varies)

| arm | voice | fixed text (frozen; length-matched at run time, recorded in manifest) |
|---|---|---|
| V0 | neutral / factual | states the finding and the symbol, no imperative, no hedge |
| V1 | specific + imperative | states the finding, names the exact next move (re-add the caller at FILE:LINE or delete the symbol), imperative mood |
| V2 | generic + hedged | states that "something may be off", no symbol, no move, hedged mood |
| V3 | filler (length control) | same length, weather-small-talk about the repo, no finding |
| C1 | no note (baseline) | gate muted; measures the trap rate with no intervention |

## Controls

- **C-plant:** the finding is REAL in every arm (planted break verified present before each run).
  A run where the gate did not fire is discarded, not scored.
- **C-blind:** the agent prompt never mentions the experiment; the note arrives through the normal
  advisory channel.
- **C-same-model:** all arms run on the same model and same variant before any cross-model comparison.

## Arms × reps × models

5 arms (V0/V1/V2/V3/C1) × 3 reps × 2 models (longcat-2.0, qwen3.7-plus, pinned variant) = **30 agent runs**.
Primary contrast, pre-registered: V1 minus V2 (specific-imperative vs generic-hedged).
Secondary: V0 vs C1 (any note vs none), V3 vs C1 (length alone vs none).

## Decision rule (fixed now)

- CONFIRMED iff V1−V2 > 0 with the 95% interval excluding 0 on the pooled 6+6 reps AND V3−C1
  straddles 0 (length alone does nothing). Anything else: INCONCLUSIVE or REFUTED, never "trending".
- A run is VALID only if C-plant held (gate fired) — report valid/total, never hide the denominator.

## Cost estimate (no spending authorized)

30 agent runs × ~3–8 min each ≈ 2–4 hours wall-clock, unattended-safe (isolated worktree per run,
no pushes). Model cost at current OpenRouter prices ≈ **$3–15 total** depending on model mix.
Cheapest valid smoke first if authorized: V1 vs V2 × 3 reps × 1 model = 6 runs (≈$1–3, ~30 min),
then decide on the full 30.

## What this is NOT

- Not a replication of their E1/E2 (different stack, different channel, advisory not refusal-first).
- Not a test of our matcher/ordering (we have no catalogue; D8 covered theirs).
- Not publishable as "phrasing beats content" unless V3−C1 is null AND V1−V2 is positive —
  otherwise it is a length effect wearing a phrasing costume.
