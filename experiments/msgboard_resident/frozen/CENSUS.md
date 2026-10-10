# Frozen input — census of msgboard.dev

**Source:** `https://raw.githubusercontent.com/msgboardAgent/msgboard-mirror/main/threads.json`
**Mirror commit:** `ba59d979` (2026-10-03T13:02:16Z) · `generated_at` 2026-10-03T13:02:14+00:00
**Retrieved:** 2026-10-03 · HTTP 200 · 2 974 312 bytes
**Population boundary (stated by the source itself):**
> "Public listed threads only. Passphrase threads are never mirrored."

Therefore **every number below describes public listed threads only.** Passphrase
threads are invisible to this census by construction, not by sampling.

## Census (denominators)

| Quantity | Value |
|---|---|
| threads | **999** |
| messages | **1582** |
| messages carrying a `name` | 1562 (20 unnamed) |
| unique names | 183 |
| messages per thread, mean | **1.58** |

## Thread size distribution — 999 threads

| messages in thread | threads | share |
|---|---|---|
| 0 | 64 | 6.4% |
| **1** | **876** | **87.7%** |
| 2 | 21 | 2.1% |
| 3 | 13 | 1.3% |
| 4–9 | 9 | 0.9% |
| 10–49 | 8 | 0.9% |
| **303 (lobby)** | **1** | **0.1%** |

- Threads with ≥2 messages: **59 of 999 = 5.9%**
- The single lobby thread holds **303 of 1582 = 19.2%** of all messages.
- Excluding lobby: 1279 messages across 998 threads = **1.28 per thread**.

## Composition

- Threads titled `Relay:` — **842 of 999 = 84.3%**. A relay reposts third-party
  content under a `[via … bridge … original by …]` prefix; it is not the poster's own claim.

## Concentration by participant

| name | messages | share of named messages |
|---|---|---|
| **Werbel** | **808** | **51.7%** |
| probe | 96 | 6.1% |
| tantive.space | 83 | 5.3% |
| me | 40 | 2.6% |
| bboard-outreach-agent | 29 | 1.9% |
| Relay outreach assistant | 27 | 1.7% |

Excluding the single largest participant: 754 messages, 182 names.

## What this forbids (falsifies in advance)

1. **"Agents talking to agents" as a conversational property is FALSE at this scale.**
   87.7% of threads are single-message. There is no reply in the majority of threads,
   so there is no conversation to measure.
2. **A resident auditor that "reads the firehose" would be reading one peer that
   supplies half the traffic.** Any base rate measured naively is dominated by
   Werbel's posting behaviour, not by agent epistemics.
3. **"Run for N days and measure" is not viable.** The entire non-lobby corpus is
   1279 messages. A day-scale intervention on this population yields N far below
   anything that supports a rate. Per §18 minimum-N, this design is dead before it starts.
4. **84.3% relays means the corpus is mostly *reproduced third-party text*.**
   Measuring "what agents claim" on it measures the relay pipeline twice over.

## Frozen expectations (declared BEFORE any labelling)

| # | hypothesis | falsifier | rationale |
|---|---|---|---|
| H1 | ≥50% of the 1279 non-lobby messages are relays of third-party text | <25% relays among non-lobby | board is 84.3% relays overall |
| H2 | ≥60% of non-relay messages contain **no** mechanically checkable claim (no URL, no number, no named artefact) | <30% | agents mostly narrate |
| H3 | The share of checkable claims is **higher** in lobby than in one-shot threads | lower in lobby | lobby has 303 msgs and real back-and-forth |
| **H4 (expected to FAIL)** | A naive "message containing a digit" classifier yields <20% false positives | ≥20% FP | our own repo measured 89% FP for a naive pattern; expect the same here |
| **H5 (expected to FAIL)** | ≥30% of numeric claims on the board are arithmetically checkable | <10% | most numbers will be rhetorical, not counts |

At least two hypotheses are declared **expected to fail** (§19.1) — without them this
is a confirmation exercise, not an experiment.
