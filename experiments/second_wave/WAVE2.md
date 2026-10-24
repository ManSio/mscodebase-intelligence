# Second wave (2026-10-06, evening) — red team, research sweep, hostile review, D9

All four ran in parallel, no LLM in any measurement loop, nothing committed by the agents except
D9's implementer working in this worktree (reviewed, tested, committed as `babaa488`).

## 1. Red team on the whole line (7 attacks)

| # | Attack | Verdict | Required fix |
|---|---|---|---|
| 1 | D8 "72/72 zero divergences" — 36 cells are empty-empty; arms correlated (same reader); fixtures synthetic | LANDS | Report 36/36 non-empty separately; "transcription check, not independent invention" |
| 2 | H4 CONFIRMED in the table, downgrade only in the diary | LANDS | Verdict cell → CONFIRMED-NARROW; freeze a nonzero-gap cross-tier act |
| 3 | Exp 29 "design clean" travels as endorsement of unverified headlines; 432-vs-380 gap open | PARTLY | Every citation carries "intervals NOT re-derived"; send the 6-item file request |
| 4 | Co-authorship offer still cites withdrawn numbers (comment 5903141209 unedited) | LANDS | Correct on-thread; only 1-V proxy goes in; silent-sensor excluded without raw |
| 5 | Published comments: phantom quote, hash mismatch, phantom comment id, unopenable referents | LANDS (1 FATAL: "eleven days") | 11-item minimal edit set (see §4) |
| 6 | "11 days before you shipped" — wrong count, wrong date, priority single-sourced | LANDS on count+date | Strike day-counts; priority = their confirmation, not our sweep |
| 7 | H5 rescored post-freeze + H12 on unfrozen F1m/F2m counted as wins | PARTLY | Headline "9 CONFIRMED as frozen, 1 rescored, 1 auxiliary" |
| — | Failed attacks (kept): H11 classification, trap blindness analysis, E11 pre-look provenance | — | no action |

## 2. Research sweep (all sources fetched this session)

**Cite:**
1. Ho et al. 2022, Choosing Wisely cluster RCT (5/5 null) — the causal null our JIT notes must
   beat; design implication: bundled intervention, not reminders alone.
2. Agora/LoCoMo 2026-06-30 (recency 0.024; BM25 ≈ vector; hybrid +0.057, +0.012 at k=5) + BEIR
   2021 — lexical-first justified with the small-k caveat.
3. Control Illusion (order effects modest/inconsistent) + vendor docs (GPT-4.1 later-wins;
   Anthropic +30% query-at-end) — order matters conditionally and per-model.

**Stop saying:**
1. "Short specific notes beat generic notes" — no causal evidence; the only large-n instruction
   study is ~50/50.
2. "LLM judges are tone-sensitive" unqualified — rubric-strict judges resist style bias.
3. "Lost in the Middle tells us where to inject" — no study maps retrieval-position to
   tool-stream injection position.

Adversarial nulls found: Instructions-as-Code (27.7% up vs 26.35% down); C. Illusion Table 8
(ordering modest/inconsistent); tkarim45 llm-judge-bias (small-n: position 0.000, verbosity 0.750,
confident 1.000 — supporting, not conclusive). Two searches failed with HTTP 429 (disclosed, not cited).

## 3. Hostile review of our two GitHub comments

56 sentences reviewed: **40 DEFENSIBLE, 16 ATTACKABLE (1 FATAL, 10 SERIOUS, 5 NIT)**.
Most dangerous: C2-27 ("found it independently and eleven days before you shipped") — the count is
false and Tom corrected it in-thread. Verdict: **NO-GO as they stand**; 11-item minimal edit set
recorded in the agent report. Independently verified by the reviewer: the 1-V proxy ladder
recomputes from the two JSON files; all 8 F4b symptom failures are item #3.

## 4. D9 — our delivery telemetry (implemented, tested, committed)

Log moved out of `%TEMP%` to `<data_root>/projects/<hash8>/gate_telemetry.jsonl` (override kept).
Every evaluation emits one JSONL row from the deciding branch (no second code path):
delivered + reason + restraint detail. Python returns new keys only.
Tests: 13 pytest + 42 node, full suite 2072 passed, ruff clean, golden behavior proof identical.
Left out: TS-side redact of 200-char act text (documented residual); old temp log untouched.
Commit: `babaa488`.

## 5. M4 — tone experiment (DESIGNED, NOT RUN)

`experiments/note_tone_m4/frozen/DESIGN.md`: 5 arms × 3 reps × 2 models = 30 agent runs,
primary contrast V1−V2, length control V3, illusion-of-compliance guard (score the artifact).
Estimate $3–15 / 2–4 h; smoke 6 runs $1–3. Starts only on the owner's explicit budget word.
