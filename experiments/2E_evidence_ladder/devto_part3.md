# We Attacked Our Own LLM Memory-Verification Experiment. The Dataset Was Lying.

*Part 3 of the memory-verification series. Part 1: [The Mechanical vs. The Semantic: What Happens When AI Memory is Wrong?](https://dev.to/mansio/the-mechanical-vs-the-semantic-what-happens-when-ai-memory-is-wrong-38ko) · Part 2: [Your memory layer is lying to you (and your LLM agrees)](https://dev.to/mansio/your-memory-layer-is-lying-to-you-and-your-llm-agrees-1oia)*

In Part 2 we showed that giving an LLM 25 lines of real code instead of bare anchor strings jumps recall from 0.08 to 0.88 (×11). The one remaining hole was the **present-trap**: the model sees the right token in the wrong context and says "true".

This post is the story of what happened when we tried to close that hole with structural evidence — a call graph, ownership, imports. We built a ladder of evidence formats, ran 744 API calls across 5 arms, and then **attacked our own experiment**. The attack found that our dataset was lying: 4 of the 6 "false" trap facts were actually true. And correcting the labels inverted our headline conclusion.

## The Evidence Ladder

One dataset (50 facts: 25 true / 16 absent / 6 trap / 3 silent), one prompt skeleton, one variable — the form of evidence. Three models: qwen3.7-flash, deepseek-v4-flash, glm-4.7-flash.

| Rung | Evidence form | What the model sees |
|---|---|---|
| 1 | `code_first` | bare anchor strings (`["typesense"]`) |
| 2 | `file_content_first` | 25 lines of the real file around the anchor |
| 3 | `graph_first` | serialized structure: definitions, imports, callers/callees, occurrence lists |
| 3b | `file_graph_first` | file fragment + structure (the "why not both?" arm) |
| 4 | `temporal_first` | structure + git provenance (commit, date, branch, "existed until C") |

Verdict schema: `{"verdict": "true"|"false"|"unknown"}`, temp=0, seed=42, zero-shot. Leak-guard asserts ground truth never enters the prompt.

## Rungs 1→2: evidence format beats model

The ladder's base case reproduced cleanly on a fresh model set:

```
qwen3.7:    recall(real) 0.24 → 0.92   FA 0.00 → 0.02
deepseek:   recall(real) 0.04 → 0.84
glm-4.7:    recall(real) 0.60 → 0.68
```

Token strings are not evidence. Code is. (Confirmed against Part 2's V4 run: qwen3.7 file_content matched run-to-run, recall 0.92 vs 0.88.)

## Rung 3: graph closes the trap. Or so we thought.

Graph evidence (for stdlib-ish tokens like `logging`: a list of the 109 files it occurs in, instead of one fragment) gave qwen3.7 **FA = 0.000** — including zero false accepts on the trap category. We wrote the pre-registered interpretation: "structural layer closes the present-trap failure mode."

Then rung 3b, the hybrid. Adding the file fragment back **reopened the trap** (FA 0.02, same R45 as before). Not additive: fragment presence dominates graph structure. For qwen, "both" is strictly worse than "fragment only" (accuracy 0.900 vs 0.940).

That's a useful negative result on its own: don't blindly concatenate evidence formats. But we weren't done — the user of this series asked us to red-team the experiment.

## The attack: the dataset was lying

Red-team checklist, item 1: *attack the ground truth, not the model.* We grepped the six "present-trap" facts — claims like "The server wrapper uses logging", labeled false because the mutation generator replaced the real value with a stdlib import that exists *somewhere* in the project.

| Fact | Claim (labeled FALSE) | Reality in code |
|---|---|---|
| R43 | "The knowledge graph uses re" | `graph.py:31: import re` + 2 usages → **TRUE** |
| R45 | "The server wrapper uses logging" | `server.py:14: import logging` → **TRUE** |
| R46 | "The watchdog uses threading" | `watchdog.py` + `threading.Lock()` → **TRUE** |
| R47 | "Hub model loading uses pathlib" | 6 occurrences → **TRUE** |
| R44 | "Cross-project search uses pathlib" | imported, never used → **ambiguous** |
| R42 | "The server wrapper uses dataclasses" | 0 occurrences → correctly FALSE |

**4 of 6 "traps" were true.** The generator validated `value != real_value` but never checked that the value was absent from the *subject*. The models that "false-accepted" them were right; the ground truth was wrong.

### Corrected matrix (true pool = 25 real + 4 trap-true = 29, false pool = 20)

| arm | qwen3.7 rec/FA | deepseek rec/FA | glm rec/FA |
|---|---|---|---|
| code_first | 6/29, 0/20 | 1/29, 0/20 | 18/29, 5/20 |
| file_content | **24/29**, 0/20 | 23/29, 1/20 | 20/29, 1/20 |
| graph_first | 19/29, 0/20 | 13/29, 0/20 | **25/29**, 1/20 |
| file_graph | 22/29, 0/20 | **24/29**, 1/20 | 24/29, 1/20 |

**Inverted conclusions:**

1. **"Graph closes the present-trap" is an artifact.** qwen3.7's graph arm didn't filter false claims — it *rejected all four true trap claims* (fail-closed on the category). The graph made qwen more conservative, and the mislabeled data made that look like precision.
2. **glm-4.7-flash, which Part 2 told us to exclude as fail-open, is the best structural verifier in the series**: recall 25/29, FA 1/20 on graph evidence. Its weakness was anchor-strings, not evidence-processing.
3. **The best evidence format is model-specific**: fragment for qwen, graph for glm, hybrid for deepseek. There is no global winner.

This is the uncomfortable part of publishing honest numbers: your headline can survive a reviewer but die on your own grep.

## Rung 4: git provenance — "was true then" vs "true now"

New dataset from git archaeology (48 facts: 12 symbols removed after commit C / 28 real / 8 never-existed; ground truth validated via `git show C~1`). Evidence: structure at HEAD + "existed until commit C (date, subject, branch)".

```
deepseek:  48/48, FA = 0.000
glm:       48/48, FA = 0.000
qwen3.7:   43/48, FA = 5/12 removed (accepted "existed until" as "exists")
```

Commit + date + branch lets 2/3 models distinguish past from present perfectly. qwen3.7 confuses "existed until C" with "exists" on 5/12 removed facts — no pattern by date or commit (T04 and T05 share a commit, different verdicts). Looks like model-specific weakness in temporal negation, hard to fix with prompt format.

Caveat we're keeping honest: these are existence claims ("symbol X is defined in file F"), which are easier than the usage claims ("X uses Y") of the v4_rep dataset. The two datasets are complementary, not interchangeable.

## Determinism: pin the provider (thank you, comment section)

Part 2's known weakness #1: temp=0 + seed=42 on OpenRouter is not determinism — ≥8 upstream backends, measured swing ±0.05–0.10 (nemotron FA 0.18 → 0.08 between identical runs). Our plan was K≥3 repeats (~4200 calls, $2–5).

In the comments, Tom Jones shared exactly this problem from his own benchmark — same 400 prompts, endpoint pinned vs not: llama-3.3-70b 95.5% vs 78.2% (17.3-point swing!), gpt-oss-120b 0.6 points. His note: OpenRouter accepts `provider.order` with `allow_fallbacks: false`, which pins the endpoint and takes routing out entirely — much cheaper than K≥3 repeats.

We probed it: 3 facts × 3 repeats, pinned [Alibaba] vs unpinned, qwen3.7-flash. Every response confirms `"provider": "Alibaba"`, verdicts stable 3/3 in both configs (qwen already routed to Alibaba by default — the swing is a multi-backend-model problem, nemotron/glm style). The harness now supports `--pin-provider`; a full pinned rerun costs ~$0.03 instead of $2–5. Adopt it.

## What this means for verify-on-read

1. **Evidence format is a per-model knob, not a global constant.** Measure yours: fragment-first for qwen-family, graph-first for glm-family, hybrid for deepseek.
2. **Do not concatenate evidence formats blindly.** For qwen, file+graph was strictly worse than file alone.
3. **Git provenance is a cheap, powerful temporal signal** (2/3 models at 100% on existence claims) — but don't rely on it for every model family.
4. **Red-team your dataset before trusting your metrics.** One grep on the subject files inverted our headline. The "present-trap" category in our public dataset is partly a measurement artifact — we're disclosing it here rather than letting it quietly inflate future papers.
5. **Pin providers in production VOR runs.** Cheaper than repeats, removes a confound you can't see in single-pass numbers.

## Reproduce

Harness: `scripts/run_1L_live_arm.py` (arms code_first / file_content_first / graph_first / file_graph_first / temporal_first, `--ev-contexts`, `--facts`, `--pin-provider`). Contexts builder: `graph_context_builder.py`; temporal generator: `temporal_facts_generator.py` (ground truth from `git show C~1`, no LLM). Full report with raw outputs: `experiments/2E_evidence_ladder/report.md`. Tests: 56 for the harness/builder/generator, 1265 total, all green.

Dataset fingerprint v4_rep: `820bbbf60a0fc930` · temporal: `e3c1fdd4` · calls: 744 · est. cost: ~$0.014.

*Also responding to the comment section of Part 1: Skillselion's manifest anchoring (`pkg:` anchors — closed world, absence is evidence) and Cophy's write-time invalidation triggers are both on our roadmap; UnitBuilds' write-time triple validation (A+B=C) is the write-path complement to our read-path verification — the temporal-provenance experiment here is our first step toward the "archive vs refute" question that ended that thread.*
