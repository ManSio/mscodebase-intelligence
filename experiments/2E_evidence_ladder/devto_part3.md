---
title: "We Attacked Our Own LLM Memory-Verification Experiment. The Dataset Was Lying."
published: false
description: "We red-teamed our own memory-verification experiment: 4 of 6 'false' trap facts were true, the conclusions inverted, and the real fix for temporal claims was a verb tense."
tags: ai, agents, testing, mcp
---

# We Attacked Our Own LLM Memory-Verification Experiment. The Dataset Was Lying.

*Part 3 of the memory-verification series. Part 1: [The Mechanical vs. The Semantic: What Happens When AI Memory is Wrong?](https://dev.to/mansio/the-mechanical-vs-the-semantic-what-happens-when-ai-memory-is-wrong-38ko) · Part 2: [Your memory layer is lying to you (and your LLM agrees)](https://dev.to/mansio/your-memory-layer-is-lying-to-you-and-your-llm-agrees-1oia)*

Giving an LLM real code instead of bare anchor strings jumps memory-claim verification from recall 0.08 to 0.88 (×11). The one hole left was the **present-trap**: the model sees the right token in the wrong context and says "true".

So we tried to close it with structural evidence — then **attacked our own experiment**. The attack found the dataset was lying: 4 of the 6 "false" trap facts were actually true. Correcting the labels inverted every conclusion. Then a temporal follow-up showed the models can't tell "was true then" from "true now" — until you phrase the question in the right tense. And a provider-pinned re-run confirmed it all survives routing. (~1900 calls, < $0.10.)

## The Evidence Ladder

One dataset (50 facts), one prompt skeleton, one variable — the form of evidence. Three models: qwen3.7-flash, deepseek-v4-flash, glm-4.7-flash.

| Rung | Evidence form |
|---|---|
| 1 | bare anchor strings |
| 2 | 25 lines of the real file around the anchor |
| 3 | serialized structure: definitions, imports, callers/callees, occurrence lists |
| 3b | file fragment + structure (the "why not both?" arm) |
| 4 | structure + git provenance |

Verdict schema: `{"verdict": "true"|"false"|"unknown"}`, temp=0, seed=42, zero-shot, leak-guarded.

## Rungs 1→2: evidence format beats model

```
qwen3.7:    recall(real) 0.24 → 0.92   FA 0.00 → 0.02 (old labels; that 0.02 was a mislabeled true fact — corrected FA = 0, see below)
deepseek:   recall(real) 0.04 → 0.84
glm-4.7:    recall(real) 0.60 → 0.68
```

Token strings are not evidence. Code is. (Reproduced on the corrected dataset, pinned: qwen 0.88.)

## Rung 3: graph closes the trap. Or so we thought.

Graph evidence gave qwen3.7 **FA = 0.000**, including zero false accepts on the trap category. We wrote the pre-registered interpretation: "structural layer closes the present-trap failure mode." Then rung 3b, the hybrid, **reopened the trap** (FA 0.02, the same fact as before — which, as the red team below shows, was actually *true*: that "false accept" was a label artifact, not a model failure). Not additive: fragment presence dominates graph structure. For qwen, "both" is strictly worse than "fragment only".

## The attack: the dataset was lying

Red-team checklist, item 1: *attack the ground truth, not the model.* We grepped the six "present-trap" facts — claims like "The server wrapper uses logging", labeled false because the mutation generator replaced the real value with a stdlib import that exists somewhere in the project.

| Fact | Claim (labeled FALSE) | Reality |
|---|---|---|
| R43 | "The knowledge graph uses re" | `graph.py:31: import re` + 2 usages → TRUE |
| R45 | "The server wrapper uses logging" | `server.py:14: import logging` → TRUE |
| R46 | "The watchdog uses threading" | `watchdog.py` + `threading.Lock()` → TRUE |
| R47 | "Hub model loading uses pathlib" | 6 occurrences → TRUE |
| R44 | "Cross-project search uses pathlib" | imported, never used → ambiguous (excluded) |
| R42 | "The server wrapper uses dataclasses" | 0 occurrences → correctly FALSE |

**4 of 6 "traps" were true.** The generator validated `value != real_value` but never checked the value was absent from the *subject*. The models that "false-accepted" them were right; the ground truth was wrong. We created a corrected copy (29 true / 20 false / 1 ambiguous, new fingerprint) and kept the original untouched as a historical artifact.

*Honest gap: we corrected the **labels**, not the generator that produced them. The v4 generator still checks `value != real_value` instead of subject-scoped absence — the corrected dataset is a re-label, and our process rule (P-00X) now requires subject-file grep validation for any synthetic category.*

### Corrected matrix, pinned re-run (routing eliminated)

| arm | qwen rec/FA-tr/miss | deepseek rec/FA-tr/miss | glm rec/FA-tr/miss |
|---|---|---|---|
| file_content | **0.88**/0/**3** | 0.80/1/2 | 0.68/2/1 |
| graph_first | 0.72/0/**4** | 0.48/0/2 | **0.84**/1/**0** |
| file_graph | 0.84/0/3 | **0.92**/1/2 | 0.80/2/1 |

Columns: **recall** — true claims correctly accepted / 25 real; **FA-trap** — false accepts on the trap category (only R42 is genuinely false after relabeling); **miss_true** — true trap claims wrongly rejected (hidden recall loss, invisible under the old labels).

FA trap counts only R42 (the one genuinely false trap claim). For context, Part 2's headline conclusions were: graph evidence closes the present-trap; qwen3.7 is the safe choice (FA 0.00 zero-shot, recall 0.88 with file content); glm-4.7 is dangerously fail-open (FA 0.24 zero-shot). **Inverted conclusions:**

1. **"Graph closes the present-trap" is an artifact.** qwen's graph arm didn't filter false claims — it rejected all four *true* trap claims (miss_true 4/5, hidden recall loss invisible under the old labels).
2. **glm-4.7, which Part 2 told us to exclude as fail-open, is the best structural verifier in the series**: recall 0.84, FA trap 1, **miss_true 0** on graph evidence.
3. **The best evidence format is model-specific**: fragment for qwen, graph for glm, hybrid for deepseek. No global winner.

### But the trap is real (extended category, subject-validated)

One false trap fact (R42) is statistically meaningless, so we extended the category with a **fixed generator (P-00X)**: false-trap = value present in the project (≥2 files) but absent from the *subject file* (grep = 0). 20 false / 10 true facts, pinned run:

| arm | qwen FA/rec | deepseek FA/rec | glm FA/rec |
|---|---|---|---|
| file_content | 2/20, 2/10 | **15/20**, 6/10 | 13/20, 7/10 |
| graph_first | 2/20, 3/10 | **8/20**, 5/10 | 14/20, 9/10 |

The present-trap is **NOT a label artifact**: on honest labels, file_content false-accepts 10–75% of "X uses Y" claims (deepseek 15/20, glm 13/20). And **graph evidence halves deepseek's false-accept rate (15/20 → 8/20)** — the "graph doesn't close the trap" conclusion from the N=1 v4_rep was itself a small-sample artifact. It just doesn't help glm (14/20), and qwen was already at 2/20 (paying with recall 2/10).

### The corrected 1-L re-score (3300+ historical calls, no re-billing)

We taught the summary tool to recompute metrics from old progress files + corrected truth (verdict-by-id, manually audited — zero field drift). The real 1-L picture:

- **True trap-FA (R42): 0 for every model.** The "present-trap FA 0.02–0.04" in Part 2 was mislabeled data — models were right.
- **Hidden trap miss_true: qwen/deepseek 4/5** — fail-closed models rejected true usage claims. This loss was invisible in the old metrics.
- Real fail-open is absent/silent: glm code_first 7+2.

## Temporal: "was true then" vs "true now"

The present-trap wasn't only about wrong labels. Digging deeper exposed a harder problem: **models cannot distinguish "X exists now" from "X existed then"** — unless the question itself carries the tense.

We built a temporal dataset from git archaeology (48 facts: 12 symbols removed after commit C / 28 current / 8 never-existed, ground truth from `git show C~1`).

**E4 (git provenance in evidence):** qwen3.7 43/48, deepseek/glm 48/48. Seemed like provenance worked — 2/3 models perfect.

**E4b (blind control, no git strings):** **all three models 48/48.** Git provenance was not just unnecessary — it *hurt* qwen ("existed until C" suggests existence, a token-presence trap in the evidence).

**E4c (duo design, no hints):** one neutral evidence block (HEAD state + "SYMBOLS in F at history" from `git show C~1`), two questions:

```
NOW  ("X is defined in F"):   removed FA: qwen 12/12, glm 12/12, deepseek 9/12
PAST ("X WAS defined in F"):  all three 40/40
```

**Temporal present-trap is universal.** When the evidence mentions X in history and the question is about the present, every model says "true" (12/12, 9/12, 12/12) — a model cannot distinguish "X appears in the evidence" from "X exists now". But phrasing the question in the past tense solves it completely (40/40). The E4b conclusion ("qwen is fragile, deepseek/glm are robust") was itself an artifact of the "NOT FOUND AT HEAD" hint — without it, nobody is robust.

## Determinism: pin the provider (thank you, comment section)

Part 2's known weakness: temp=0 + seed=42 on OpenRouter is not determinism — ≥8 upstream backends. Tom Jones' comment suggested `provider.order` with `allow_fallbacks: false`, which pins the endpoint — cheaper than K≥3 repeats.

We probed it: **StreamLake — the most-used upstream for glm in our server CSV (245 calls) — returns 404 "No endpoints found" when pinned: it no longer serves this model at all.** Cloudflare/DeepInfra are stable. The full pinned re-run (qwen→Alibaba, deepseek/glm→DeepInfra, ~$0.02) reproduced every conclusion: per-model arm rankings, temporal present-trap (12/12, 9/12, 12/12), past-tense fix (40/40), and FA absent/silent = 0 across evidence arms. One caveat: glm stays non-deterministic even pinned (FA 0.06 → 0.02 → 0.02 across runs) — part of that is model variance, but part is **upstream drift**: unpinned glm now routes to DeepInfra (not StreamLake), so cross-day comparisons mix changing backends. Pinning removes routing variance at a point in time, not model or availability drift over time.

*Reproduction note: if you reproduce pinned runs, avoid StreamLake — it was the top unpinned provider for glm in our server CSV but returns 404 when pinned (no endpoint for the model; upstream availability drifts). Pinning to a provider that serves you well unpinned is not guaranteed to work; probe before committing to a long run.*

## What this means for verify-on-read

1. **Evidence format is a per-model knob.** qwen-family: file fragment (recall). glm-family: graph (recall + trap precision). deepseek: hybrid.
2. **Do not concatenate evidence formats blindly.** For qwen, file+graph was strictly worse than file alone.
3. **Red-team your dataset before trusting metrics.** One grep on the subject files inverted our headline. Synthetic categories must be validated *per subject*, not per project — and FA on a category is meaningless until the category's labels are truth-checked.
4. **Temporal questions must be phrased in time.** "Is X defined in F?" with history in evidence fails universally (12/12, 9/12, 12/12); "Was X defined in F?" succeeds (40/40). For existence checks: HEAD-only evidence, or explicit tense.
5. **Pin providers in production runs.** Cheaper than repeats, and it protects against "popular but broken" upstreams (StreamLake).

## The meta-lesson

The most dangerous assumption in LLM evaluation isn't the model — it's the dataset. We spent ~$0.10 and ~1900 calls to learn that 4 of 6 "false" facts were true. Before you trust any LLM benchmark, ask: **who labeled the ground truth, and did they verify it per-example or per-category?** We didn't — we validated the trap category against the *project*, not the *subject*. One grep on subject files inverted every conclusion.

> **Synthetic categories must be validated *per subject*, not per project.** A value that exists anywhere in the repo is not evidence that the *subject* of the claim uses it. Check the subject's file.

## Known weaknesses (post-red-team)

1. **Fact order matters (measured).** Facts are stored block-ordered (R01–R25 true, R26–R50 false). A shuffled control run (qwen code_first, seed 123) changed 4/50 verdicts vs the original order — no systematic direction, but ~8% sensitivity to order. Shuffle-seed in future runs.
2. **Trap category size matters.** After relabeling, v4_rep has one genuinely false trap fact — but an extended subject-validated category (E5, 20 false) shows the present-trap is real and mass-scale (file_content FA 10–75%). Metrics from N=1 are flags, not rates.
3. **Language confound (unchecked).** Claims are Russian, instructions English. Part 2 showed prompt language shifts unknown rates (deepseek 0.94→0.54). A Russian-instruction control was not run for this series.
4. **Decoy frequency.** 19 facts share the same control symbol block; models could pattern-match repetition. Not controlled.
5. **Temporal claims are existence claims.** Easier than usage claims (v4_rep); the two datasets are complementary, not interchangeable.
6. **Small N, wide CIs.** 6 trap facts, 12 removed facts. Headline arm rankings rest on differences of 2–3 facts out of 25.
7. **Upstream drift across days.** Unpinned vs pinned runs happened ~12h apart; glm's routing changed (StreamLake → DeepInfra). Cross-day numbers mix backends.

## Reproduce

Harness: `scripts/run_1L_live_arm.py` (arms code_first / file_content_first / graph_first / file_graph_first / temporal_blind_first / temporal_duo_first; `--facts`, `--ev-contexts`, `--pin-provider`). Summaries: `scripts/summarize_1L_categories.py --facts <corrected.json>` (truth-based re-score of old runs). Full report with raw outputs and the red-team audit: `experiments/2E_evidence_ladder/report.md`. Tests: 64 for harness/builder/generator/summarize, 1265 total.

Dataset fingerprints: original `820bbbf60a0fc930` (historical, mislabeled trap) · corrected `e6ce7b902d0a20a9` (29 true / 20 false / 1 ambiguous) · temporal `e3c1fdd4` / `d1d2c2ed440ec370` · calls: ~1900 across the series · est. cost: < $0.10.

*Also responding to the comment section of Part 1: Skillselion's manifest anchoring (closed-world `pkg:` anchors) is **implemented**, not planned — ADR-0005, typed manifest anchors closed 7 false REFUTEDs in our 1-M experiment (credited in the ADR); Cophy's write-time invalidation triggers remain on our roadmap; Glen Allen's freshness-as-dependency is exactly what E4b exposed — a git string kept a stale truth alive inside the evidence, so freshness must apply to the *evidence*, not just the memory node; 473185670's forward-looking claims (trading signals, PENDING → Resolution Loop) are the mirror direction — our temporal series covers "was true then" vs "true now", their loop covers "will it be true" — the same retrieval-boundary problem, mirrored in time. UnitBuilds' write-time triple validation (A+B=C) is the write-path complement to our read-path verification: even with perfect provenance, the active agent's context window cannot be the source of truth, and neither can a tense-ambiguous claim.*
