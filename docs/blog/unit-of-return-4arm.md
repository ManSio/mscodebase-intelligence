---
title: "The Unit of Return: a 4-Arm Retrieval Experiment on a Real Codebase"
published: false
tags: ai, rag, python, architecture
---

## Where It Started

The problem to which everything traces back: **RAG search across an unfamiliar codebase sees the code, but misses the intent.** Embeddings find a chunk by keywords, PropertyGraph finds a symbol by name, but to the question "where is the real business logic here, and what can I safely throw away?" no model answers — because the answer does not exist in static code representation.

Hence the **bootstrap pipeline** for indexing a new project (background results cited in the table below; the new experiment stands on them):

1. **Entities** — types and data-classes as the domain backbone;
2. **Entry points** — decorators (`@mcp_app.tool`) as the system boundary;
3. **Tests as ground truth** — the only deterministic way to say *"this function is part of live execution logic"*;
4. **Git → ADR** — decision history extracted from commit logs.

Step 3 was the battleground. "A test has a name, a function has a name, let's link by name" died at **0 out of 109 candidate name-matches in the evaluation sample**. A custom `sys.settrace` plugin traced all 1,727 tests: 1,551 (89.8%) execute ≥1 src function, 1,212 unique functions, **10.1 mean across executing tests (median 6, range 1–118)** — "1 test = 1 function" was a myth, so edges needed no ranker: `TESTS` edges are the raw traced call set under Exp-7 filters; no ranker needed for inclusion. Tarantula ranking was refuted as a selector (rank≤3 covered only 22.6% of tests) but kept as a confidence annotation. `coverage.py` lost to the lightweight plugin (coverage.py +19.96% vs plugin +13.6%, same session, median of A/B runs). Static signals reached 70% union recall on the dynamic-trace gold set but stayed a companion, not a driver. Portability held on foreign Python repos (97.3% (gemma_agent, 2805/2882) to 100% (commit-, 27/27) linked). E17 closed the loop into search: up to 3 covering tests appended per function at `graph_score` 0.4 (weight of the TESTS group vs 1.0 for definitions; E17 shipped 0.4 as an operating point with MRR held, ablation vs BM25/reranker not run), definitions never displaced (`MRR = 1.0` both arms), 5/5 red-team attacks repelled — but hit@1 did not move. TESTS-signal (covering-test names appended as secondary context) is **context for the LLM, not a search improvement**.

That last line is where the new question starts: if retrieval finds the file and the reader still fails, which half is broken?

Background results cited (all from the bootstrap-pipeline notes, same repo):

Quoted from the bootstrap study, not re-measured here.

<table style="border-collapse: collapse; width: 100%; margin: 1em 0;">
<thead>
<tr>
<th style="border: 1px solid #ddd; padding: 8px; background-color: #4a90e2; color: white; text-align: left;">Exp</th>
<th style="border: 1px solid #ddd; padding: 8px; background-color: #4a90e2; color: white; text-align: left;">n</th>
<th style="border: 1px solid #ddd; padding: 8px; background-color: #4a90e2; color: white; text-align: left;">result</th>
</tr>
</thead>
<tbody>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">7 (name-match → trace) (d74785d4)</td>
<td style="border: 1px solid #ddd; padding: 8px;">109-sample / 1727 traced</td>
<td style="border: 1px solid #ddd; padding: 8px;">0/109 name-match; 1551/1727 execute ≥1 src function; 10.1 mean (median 6, range 1–118)</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">7b (Tarantula) (e198b716)</td>
<td style="border: 1px solid #ddd; padding: 8px;">traced tests</td>
<td style="border: 1px solid #ddd; padding: 8px;">rank≤3 covers 22.6% — refuted as selector, kept as annotation</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">8 (coverage.py vs plugin) (c9de08e5)</td>
<td style="border: 1px solid #ddd; padding: 8px;">same-session A/B</td>
<td style="border: 1px solid #ddd; padding: 8px;">+19.96% vs +13.6% overhead — plugin wins</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">9 (static union) (71c9042d)</td>
<td style="border: 1px solid #ddd; padding: 8px;">dynamic-trace gold set</td>
<td style="border: 1px solid #ddd; padding: 8px;">70% union recall — companion, not driver</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">16 (portability)</td>
<td style="border: 1px solid #ddd; padding: 8px;">2882 + 27 tests</td>
<td style="border: 1px solid #ddd; padding: 8px;">97.3% (2805/2882) to 100% (27/27) linked</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">E17 (TESTS-signal) (c1fb2363)</td>
<td style="border: 1px solid #ddd; padding: 8px;">7-query + 35-query panels</td>
<td style="border: 1px solid #ddd; padding: 8px;">MRR held (1.0 / 0.957); hit@1 unmoved; graph_stage +15.3% wide panel</td>
</tr>
</tbody>
</table>

## The Question

A public benchmarking discussion brought a clean table: identical retriever, store, query and ranking, only the returned unit varied — ten chunks 9/14, whole document 5/14, no retrieval 6/14 correct-or-partial (their scale, their reader) — with the one count that survived being a chunk ranker's top hit landing on the answer document 0 times out of 14 (numbers and protocol credit: Tom Jones, in discussion). The claim: the unit of return is a measurement variable, not a retrieval setting. The protocol that came with it — four arms, frozen everything, plus the two controls nobody includes (oracle, closed book) — is what we ran below.

We ran it.

## F5 Design (frozen before the run)

F5 is a controlled pilot (n=16 frozen queries, 160 evaluations per arm): 16 queries × 4 arms × 10 trials = 640 verdicts (×2 LLM calls each: reader + judge). Directions, not effects.

<table style="border-collapse: collapse; width: 100%; margin: 1em 0;">
<thead>
<tr>
<th style="border: 1px solid #ddd; padding: 8px; background-color: #4a90e2; color: white; text-align: left;">Field</th>
<th style="border: 1px solid #ddd; padding: 8px; background-color: #4a90e2; color: white; text-align: left;">Value</th>
</tr>
</thead>
<tbody>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">Queries</td>
<td style="border: 1px solid #ddd; padding: 8px;">16 frozen (8 code + 8 prose), sha256 <code>e048aa12d36d95fb6d252de015d0ae807cbbce718e9c78effcd334f7c3ce83cb</code> (full sha from <code>experiments/4A_unit_of_return/frozen/f5/manifest.json</code>), overlap check: frozen_overlap_check.py v2 → OVERLAP: PASS</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">Index</td>
<td style="border: 1px solid #ddd; padding: 8px;">snapshot (taken 2026-09-26): 10,106 chunks / 716 files / 14,099 symbols; NOT hard-frozen — drift between runs, see Red Team</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">Retriever</td>
<td style="border: 1px solid #ddd; padding: 8px;"><code>mode=quality, limit=10</code>: BM25 + dense + FTS5 + graph-signal tiers, 3-way RRF (Reciprocal Rank Fusion over the three lexical/dense/graph rankers), BGE-M3 reranker</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">Arms</td>
<td style="border: 1px solid #ddd; padding: 8px;">A: top-10 chunks; B: top-1 doc, full text; C: gold file chunked to the answer span; D: empty context, same prompt minus context block</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">Reader</td>
<td style="border: 1px solid #ddd; padding: 8px;"><code>opencode-go/longcat-2.0</code> (model ID as pinned in the harness, Sept 2026)</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">Judge</td>
<td style="border: 1px solid #ddd; padding: 8px;"><code>opencode-go/qwen3.7-plus</code> (model ID as pinned in the harness, Sept 2026; ≠ reader, blind, identical reference), binary correct/incorrect, 10 trials, majority = ≥6/10 correct; 5/5 ties counted out; judge saw question + evidence span + candidate answer, blinded to arm label; invalid: 0/640 in t10, 1 in t5 pilot (F5S-03/B)</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">Guard</td>
<td style="border: 1px solid #ddd; padding: 8px;">model-mismatch → invalid; 0 invalid in trials=10 (one in the t5 pilot — see red team)</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">Raw</td>
<td style="border: 1px solid #ddd; padding: 8px;"><code>judged_raw.json</code> (16×4×10), aggregates beside it, t5 pilot kept as snapshot</td>
</tr>
</tbody>
</table>

## Objective Half: the Unit Did Not Move Retrieval (n=16)

```plaintext
A hit@1 5/16 (0.312) | hit@3 = hit@10 6/16
B top-1-is-gold 5/16 (0.312)
C oracle 16/16 | D closed book 0/16
avg context chars: A 4,946 · B 19,747 (3.99×) · C 7,337 · D 0
```

B top-1-is-gold 5/16 vs A hit@1 5/16 — different events (chunk hit vs doc hit), compared as direction only. C contexts are gold files only (7,337 avg chars vs B 19,747 — file-size comparison not run, so no claim on why). Nothing past top-3 ever held gold — retrieval failure, not ranking failure. Code A hit@1 4/8, prose 1/8: the two-population asymmetry is already visible before any reader is involved. Reader ceiling below is on longcat-2.0; frontier-reader rerun not run.

## Judged Half: the Unit Moved the Reader (n=160/arm)

CIs are Wilson 95%.

```plaintext
A top-k chunks:        26/160  (16.3%, CI 0.11–0.23)
B whole document:      55/160  (34.4%, CI 0.27–0.42)
C oracle:             156/160  (97.5%, CI 0.94–0.99)
D closed book:          0/160  (0.0%; 95% upper bound 1.9% by rule of three — 160 instruction-compliant "I don't know" on empty context)
majority per query-arm (strict >50%): A 2/16, B 5/16, C 16/16, D 0/16
judge non-unanimous 6/64 query-arms (9.4%); repro t5 (n=80/arm) → t10 (n=160/arm): A 16.3→16.3, B 30→34.4, C 95→97.5
```

Population split (n=80):

<table style="border-collapse: collapse; width: 100%; margin: 1em 0;">
<thead>
<tr>
<th style="border: 1px solid #ddd; padding: 8px; background-color: #4a90e2; color: white; text-align: left;">Population</th>
<th style="border: 1px solid #ddd; padding: 8px; background-color: #4a90e2; color: white; text-align: left;">A chunks</th>
<th style="border: 1px solid #ddd; padding: 8px; background-color: #4a90e2; color: white; text-align: left;">B whole-doc</th>
<th style="border: 1px solid #ddd; padding: 8px; background-color: #4a90e2; color: white; text-align: left;">C oracle</th>
<th style="border: 1px solid #ddd; padding: 8px; background-color: #4a90e2; color: white; text-align: left;">D closed</th>
</tr>
</thead>
<tbody>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">**code**</td>
<td style="border: 1px solid #ddd; padding: 8px;">5/80 (6.3%, CI 2.7–13.9)</td>
<td style="border: 1px solid #ddd; padding: 8px;">**40/80 (50.0%, CI 39.3–60.7)**</td>
<td style="border: 1px solid #ddd; padding: 8px;">76/80 (95.0%)</td>
<td style="border: 1px solid #ddd; padding: 8px;">0/80</td>
</tr>
<tr>
<td style="border: 1px solid #ddd; padding: 8px;">**prose**</td>
<td style="border: 1px solid #ddd; padding: 8px;">**21/80 (26.3%, CI 17.9–36.8)**</td>
<td style="border: 1px solid #ddd; padding: 8px;">15/80 (18.8%, CI 11.7–28.7)</td>
<td style="border: 1px solid #ddd; padding: 8px;">80/80 (100%)</td>
<td style="border: 1px solid #ddd; padding: 8px;">0/80</td>
</tr>
</tbody>
</table>

Code: 8.0× on point estimates (5/80→40/80), CIs [2.7–13.9] vs [39.3–60.7], no overlap; retrieval tied on doc-level numbers. Prose majorities per query: A 2/8, B 1/8 (strict). Prose (n=8 queries): A 21/80 vs B 15/80, CIs overlap — direction only, no effect claim; B 15/80 vs D 0/80 (upper bound 4.5%) — above closed-book in this snapshot; the strong form of the prose-collapse hypothesis (whole-doc at or below closed book) did not reproduce here: 18.8% vs 0% in this snapshot (pilot-scale).

Against the 'more text' reading: oracle contexts average fewer chars than B (7.3k vs 19.7k) yet score 97.5% — completeness of the right unit, not volume alone, drives the reader. Volume and unit stay confounded within the A/B pair itself (more text and a fuller unit move together there); separating them needs a whole-doc vs gold-span-sized-excerpt control, not yet run.

## Behind the Scenes: Three Days, One Laptop

Three days, one personal Windows machine, a single live index serving everything — no separate lab copy. Harness through opencode CLI at 4–8 threads: 640 reader calls plus the same in judge calls, then the trials=5 pilot on top. What broke on the way: one control run declared invalid and redone instead of silently kept; one symptom list lost and recovered from the session database instead of reinvented; one 0/3 that turned out to be an undercooked reasoning budget, not a model property (reran fixed, 3/3, logged as a pitfall so it never ships as a finding). Raw answers carried personal paths inherited from repo sources; normalized before commit, verdicts untouched. Public repo, so nothing is rewritten — invalid runs and snapshots sit on disk next to the real ones. No history rewrites, no cleaned-up reruns presented as first attempts.

## NodeRAG: a Second Rig, No LLM

Side rig, same question from the retrieval side: does structure beat chunks when the entry point is exact?

H: graph-BFS hit-rate beats TF-IDF on these 10 rule-queries. Frozen 10 rule-queries + 3 positive + 3 NONE controls (sha `8657a7e3949b5a3eed8f025b8086dcf539cdafacd0cd335f28e607fcf0e44f9a`) against our two long diary/log files: chunked TF-IDF top-10 vs PropertyGraph BFS depth-3. Hit denominator is the 10 rule-queries; 3+3 controls reported separately (3/3, 3/3).

```plaintext
Arm A (chunked TF-IDF): 8/10 = 80.0% hit rate, 301,981 tokens
Arm B (graph BFS):      7/10 = 70.0% hit rate, 170,140 tokens
Positive controls 3/3, NONE controls 3/3 clean → Verdict: no evidence graph wins here; token saving −43.6% noted
```

Token counts as reported by the harness (counting method in `experiments/noderag/` — word-count ×1.3 estimate over full retrieved text per query). Graph wins tokens (−43.6%), loses hits; all 3 misses returned 0 files — consistent with seed failure (seeds: the 3 missed rule-queries R1/R2/R7). Entry-point fragility, not traversal quality.

## Related Work (only what we opened)

Anthropic's Contextual Retrieval (2024) reported −49% retrieval failures (−67% with rerank) on their evals (incl. codebases) via per-chunk LLM context prepended before embedding — compatible with, not identical to, our arm-B reader effect. Jina's late chunking (2024) conditions chunk embeddings on full-document context; gains larger on longer docs in their BEIR eval — same direction, prose/long-doc only. Neither splits code vs prose; our code/prose split is ours, pilot-scale (n=16), reader-specific.

## Red Team

E17 attacks (all repelled): 10 threads × 100 calls with 0 errors; 234-test hub function at 16.1ms median; nonexistent-function query → 0 results (null-behavior check); graph closed mid-call → degraded to empty results without errors; nonexistent PropertyGraph path → 0 results (null-behavior check).

F5 self-attacks (three drew blood, all disclosed):
- **Majority tie.** One published B point rested on a 5/5 tie; restated strict (>50%) above — B prose 1/8, B ALL 5/16. Any table hiding its tie rule hides a judgment call.
- **"0 invalid".** True for trials=10, false for the t5 pilot (one invalid, F5S-03/B). Stated exactly.
- **Gold definition.** For 7/8 prose queries neither arm held gold, yet the reader scored — via duplicate translations of the same fact. Prose gold-as-document overstates miss; the judged gap measures usable information, not gold retrieval.
- **Live index.** Objective and judged runs saw different snapshots. Verdicts reproduced t5→t10; per-trial t5 contexts unrecoverable; full reproduction needs the frozen-index rerun.
- **Cheap reader.** A frontier reader may compress the 8×. Our numbers bound our reader, not readers.

## What Could Go Wrong

1. **n=16 pilot scale.** Percentages are directions, not effects — especially prose, where everything hinges on two queries.
→ Prefer CIs over bare rates; every % below carries Wilson 95%.
2. **Index snapshotted, not frozen.** Drift between runs is documented, not eliminated.
→ Freeze the index (or accept snapshot discipline) before the reader run next time.
3. **Judged noise band not re-run.** t5→t10 agreement is reproducibility, not a noise measurement.
→ Repeat the judged run before citing prose deltas.
4. **No per-arm token costs.** Only context chars recorded — no cost claim is attached to F5.
→ Measure tokens before any efficiency conclusion.
5. **`graph_score = 0.4` still unverified** against BM25/reranker interaction.
→ One-variable table before defending the constant (E17 shipped 0.4 as an operating point with MRR held; ablation vs BM25/reranker not run) — hidden tie-breaks are how published tables mislead.
6. **Cap experiment on our own logs not run.** A cap experiment on our own logs was not run; not mirrored here.
7. **TESTS-signal limits carry over** (Python-only, +15.3% graph_stage overhead on the 35-query wide panel; :0 = test nodes from dynamic trace lack line numbers; mock blindness = 10.2% of tests execute 0 src functions) — unchanged, see Background table above.

## Acknowledgments

## Acknowledgments

A huge thank you to everyone who engages with these posts in the comments. Your feedback, real-world observations, counter-examples, and benchmark numbers directly shape these experiments. This kind of open technical critique is what keeps engineering honest.

## A note on how this was written

Every experiment, bug, failure, and idea here is mine — I earned them the hard way, in production, in public. AI worked as my editor: it helped me structure thoughts and polish my English. It did not invent the facts, because it has none of its own.

No AI detectors were consulted in the making of this disclosure. They have enough trouble agreeing on what I am.

---

> **Disclaimer & Status:** draft (source-material for the article). This is not a "feature advertisement", but an honest engineering story: figures are reproducible, weak points are named, and unaddressed risks are listed in the "What Could Go Wrong" section.

---
