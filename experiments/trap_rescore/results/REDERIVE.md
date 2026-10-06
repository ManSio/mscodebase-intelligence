# REDERIVE — what recomputes from the bundle, what does not, and what to ask for

Bottom line up front: **nothing verifiable from this bundle alone** beyond
(i) pooled-rate arithmetic, (ii) rounding consistency, and (iii) the analysis
code's faithful implementation of the locked rules (PREREG_CHECK.md §4–5).
No per-run rows ship in the bundle, so neither −0.31 [−0.50,−0.11] nor −0.55
[−0.85,−0.27] can be re-derived, and neither can "380 of 380" / "hit on
11 of 12". That is the EXPECTED outcome (the bundle README says the raw
results "can be added on request") — recorded here as missing inputs, not as
a failure of the numbers.

## 1. What recomputes (executed checks, this session)

- Pooled fractions: 18/35 = 0.5143 → "0.51" ✓; 30/35 = 0.8571 → "0.86" ✓;
  29/36 = 0.8056 → "0.81" ✓ (bundle README + E1 RESULT table). Rounding honest.
- Cross-section consistency: E1 RESULT block inside `E2_prereg_amendment-2.md`
  (−0.306, CI [−0.500,−0.111], 12 tasks, 0 excluded, approach 0.972/0.972,
  pooled 18/35 vs 30/35, per-task pattern "negative on 6, zero on 6, positive
  on none") rounds exactly to the brief/README headline (−0.31,
  [−0.50,−0.11], "effect in 6 of 12, no trap worse"). SHAM-vs-NONE exploratory
  +0.028 [−0.139,+0.167] rounds to the brief's +0.03 [−0.14,+0.17] ✓.
- Independent scorer selftest EXECUTED: `scorers_independent.py --selftest`
  → `PASS: 101 independent selftest checks across 12 tasks (no sockets)`.
  The second scorer set is internally consistent on synthetic fixtures
  (pos/neg pairs per trap, refusal-only, prose-only, near-miss negatives).
- Analysis-code pure functions EXECUTED (imported standalone, no harness):
  E1 percentile indices 249/9749 (95%), E2 indices 83/9916 (98.33%),
  threshold edges on both `classify` fns, NA-task skipping in `deltas` —
  all match the locked rules (details PREREG_CHECK.md §4).
- Negative controls (expected failures, both observed): `analyse_e1.py
  --selftest` aborts at `valid_rows` line 38 with
  `ModuleNotFoundError: No module named 'lablib'` — proving the harness
  dependency is genuinely absent, not merely unused.

## 2. What does NOT recompute (and why)

- E1 primary −0.31 [−0.50,−0.11]: needs 108 per-run (approach, hit) rows.
  Absent. The task-level Δt values are not banked anywhere in the bundle.
- E2 C3 −0.55 [−0.85,−0.27] (98.33%) with "11 tasks entered": needs E2b
  per-run rows (to apply the NONE-approach ≥ 2 filter and see which task
  dropped). Absent. Which 11 entered is therefore unverifiable.
- E2 C1/C2 INCONCLUSIVE: needs E2a per-run rows. Absent.
- "Approach agreed on 380 of 380 runs": needs `runs/{e1,e2a,e2b}/
  results.jsonl` + per-run `record/` dirs + `fixture/` + `lablib`. All absent.
- "Hit agreed on every run for 11 of 12 traps" (+ t5 6-of-6 re-run note):
  same missing inputs. Note the t5 mechanism is REAL in code: primary
  `t5_hit` (`scorers_primary.py:470-471`) reads the run's own
  `out/<rows_file>`, and work dirs are stated deleted post-run — so the
  "t5 not checkable after the fact" claim is code-plausible, but the
  agreement counts themselves cannot be re-derived here.
- Numerical observation (question, not finding): design cells total
  108 (E1) + 216 (E2a) + 108 (E2b) = 432, but comparison covered 380 banked
  runs — a gap of 52 cells with no void/missing accounting in the bundle
  (E1 voids stated: none 2, helpful 1, sham 0; E2 voids unstated). Ask Tom to
  reconcile (voids? missing cells? t5 exclusions?) when requesting rows.
- Source-repo commit hashes/timestamps (result `54cbcb19`, locks, scorer
  version timing) are claims only from inside the bundle; the two
  spot-checked are (correctly) absent from the public `tjonesit/crystals`
  repo — they belong to the private source repo and cannot be confirmed here.

## 3. Scorer check (plain-words summary)

- Primary set (`scorers_primary.py`, 1278 lines, needs `lablib.Run`):
  per-trap predicates over the agent's tool-call inputs + the stand-ins'
  audited side-effect rows + worktree files. Approach ≈ "the trap's watched
  operation was audited" (e.g. an `ssm-run` row exists; an `svc` start of the
  named job; the named `svc` op audited). Hit ≈ "the audited operation shows
  the documented bad outcome" (e.g. SSM rejection string; quota 429 past the
  stated limit; release commit sweeping an archive-owned file; snapshot
  labelled current despite day-old content; train/eval split disagreeing with
  the New York-midnight boundary the scorer recomputes). Adoption ≈ "the
  lesson's fact shaped what was sent/done before trap feedback". Helpers
  deliberately read act fields (commands, paths, new strings), not the
  agent's prose (`Bash description` explicitly excluded, lines 4–8). Also
  owns peek/void detection and per-task success checks.
- Independent set (`scorers_independent.py`, 327 lines, harness-free):
  same verdict shape from side rows + fixture inputs only; one plain-words
  definition table (`DEFINITIONS`, lines 34–59) separates "reached the
  operation" from "bad outcome" per trap. Refused tool calls are excluded
  from both approach and hit (lines 178–183). Unknown traps raise instead of
  scoring clean (line 177–178).
- Comparison driver (`compare_builds.py`, 79 lines): for each banked row in
  the three sets, rebuilds the run from its record dir (falling back to the
  fixture when the work dir was deleted), scores independently, and counts
  agreement per field per task; exceptions become UNSCORABLE, never
  agreement (lines 51–53). Sound design — but with zero run records present,
  its output counts cannot be confirmed or denied from this bundle.

## 4. Blindness / leak check (bundle itself)

- Task JSONs are CLEAN: a case-insensitive sweep of all 12 files for
  answer/note markers (helpful, sham, lesson, crystal, refuse, note, FACT,
  MOVE, wrong, quota/429, MaxDocument…) found ZERO hits. A task file exposes
  only: prompt (112–233 chars, names the workspace tool/docs to use),
  trap id, watched `tool_type`, scorer function names, small params.
  No trap answer, no note text, nothing a scorer could cheat off.
- The trap ANSWERS necessarily live in the scorer files (both sets must know
  the bad outcome to judge it) — that is by design, not a leak: e.g. the
  independent set's definition table states each operation and its failure
  in plain words.
- Consequence for OUR future re-score: a fresh scorer can be built blind from
  task files + fixture + stand-in tools (as the independent set reportedly
  was). Blindness then depends on redacting the RUN RECORDS (not in bundle):
  banked rows carry arm labels, and transcripts by design store the injected
  note block as the model saw it — both must be stripped before a blind
  re-scorer sees them. Task files alone do not break blindness.

## 5. EXACT missing-file list to request from Tom (with reason each is needed)

1. `runs/e1/results.jsonl`, `runs/e2a/results.jsonl`, `runs/e2b/results.jsonl`
   (banked per-run rows: task, arm, rep, approach, hit, record pointer, ts) —
   needed to recompute every pooled fraction, every Δt, both CIs, the
   11-task C3 set, and any void accounting (reconciles the 432-vs-380 gap).
2. Per-run `record/` dirs (`meta.json`, `events.jsonl`, `side.jsonl`) for all
   banked runs, or the 380 compared subset identified — needed to re-run
   `compare_builds.py` and verify "380 of 380" / "hit 11 of 12" / t5 6-of-6.
3. `fixture/` (workspace inputs: reports/, config/, docs/, events, transcripts)
   + the stand-in tool implementations (or their audited-row schemas) — needed
   because scorers read fixture/work files (e.g. services list, transcript
   tree, event timestamps); without them most hit predicates cannot execute.
4. `tools/crystal-lab/lablib.py` (or at least `Run`, `row_invalid_reason`,
   `BASH_FIELDS`, `HARNESS_TELLS`, `OPS_DIR`, `load_task`, `read_jsonl`) —
   needed to run the primary scorers, both `analyse_*.py` end-to-end (incl.
   their selftests), and the comparison driver; also to audit the void/peek
   rules against amendment §§5.
5. The E1/E2 analysis outputs (`e1-analysis-2026-10-05.json`, `e2-analysis`
   equivalent) if kept — not strictly needed (recomputable from rows), but
   useful as a cross-check target for our recomputation.
6. Optional: void/missing-cell log for E2a/E2b (or confirmation the 52-cell
   gap is voids + t5 handling) — needed to close the §2 observation.

## 6. Population rule

Per the gate convention (§19.6/T10): this bundle contains zero run files, so
no rate is reported from it. Status: **nothing verifiable from this bundle
alone** (beyond arithmetic/rounding/code-fidelity checks in §1, which are
about the bundle's internal consistency, not about the experimental claims).
