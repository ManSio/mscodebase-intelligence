# Cost audit and the money guard (2026-10-21)

Measured from our own proxy records (every request we ever sent to Tīrtha is
logged in `runs/*/proxy_requests.jsonl` with the gateway's own cost fields).

## What our experiment cost

| item | value |
|---|---|
| requests sent by the experiment | **1 069** |
| tokens (sum) | **52 796 458** |
| measured cost | **$5.90** |
| escalated (Plus/Max) requests of ours | 15 |
| by arm A (single session) | $5.03 (46.9 M tokens) |
| by arm C (microtasks) | $0.84 (5.8 M tokens) |
| by arm D (pilot) | $0.03 (96 k tokens) |

Worst single runs:

| run | cost | tokens | requests |
|---|---|---|---|
| A-01d1cce11d_codebase_tool_block | **$3.05** | 30 039 525 | 330 |
| A-001f7d3a41_write_tools | $0.56 | 5 326 158 | 81 |
| A-17e65663b7_health | $0.38 | 3 360 935 | 58 |
| A-17e65663b7_health (2nd) | $0.28 | 2 602 614 | 50 |

One runaway session cost **$3.05** and 30 M tokens. That is the whole lesson:
a single unbounded agent loop is the only thing in this experiment that is
expensive; everything else is rounding error.

## The key's economics (from the owner's dashboard)

- Free requests: **0 left** (100/month, all used).
- Credit: **$59.25** prepaid; premium spend today $2.87 of a $5.00 daily cap.
- 1 272 requests this month: 96% served at Base, 4% moved up to Plus/Max.
- The key is **pinned to Max**, so escalated requests bill at
  $1.90 in / $5.69 out per 1M; Base-served requests beyond the free quota bill
  at $0.56 / $2.22 per 1M. Past the $5 daily cap, requests fall back to Base.

**The biggest single lever is not the experiment: it is the owner's own
interactive OpenCode.** The global config has `model: "tirtha/auto"`, so every
thinking turn of the daily driver also bills from that credit. The owner's own
principle — "keep Claude or Codex for the thinking, send the building to
Tīrtha" — is not yet applied to the thinking part.

## Guards now in the harness

| guard | where | what it does |
|---|---|---|
| request cap | `harness/proxy.py` (`max_requests`) | the proxy answers **429** instead of forwarding, once the cap is reached (default 60 per run) |
| cost cap | `harness/proxy.py` (`budget_usd`) | the same, on the accumulated measured spend (default **$0.15** per run) |
| step budget | `harness/run_corpus.py` (watchdog) | `session/cancel` when a worker exceeds `max_steps × 3` tool calls |
| answer budget | `frozen/prompts/*.md` | the answer must stay under 200 words; the diff is computed by the harness from disk, not returned by the model |

With the $0.15 / 60-request caps, the worst possible run is bounded at a few
cents instead of $3.05.

## Not run

Per the owner's instruction ("ничего прогонять не надо"), no further
experiment cells were executed after the cost audit. The state of the last
verified run set is in `results_summary.json`; the two re-run cells under the
receipt contract (A = 2/3, C = 0/3) are recorded in `RESULTS.md` and are the
reason the earlier quality claim was withdrawn.
