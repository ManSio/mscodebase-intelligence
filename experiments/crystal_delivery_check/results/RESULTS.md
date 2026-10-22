# RESULTS — crystal delivery check against `fe4e465`

Deterministic, no LLM anywhere. Arm A = my reimplementation from the documented
algorithm; Arm B = their code (`crystal_registry` / `crystal_act` from the RUN copy,
pure functions only). Honesty note: I have seen their source in a previous session,
so Arm A is an **independent computation of the documented formulas, not an
independent invention**. Agreement is still informative (two implementations of the
same spec over 18 acts × 2 modes × 2 replays), and any disagreement would have been
reported as instrument divergence.

Object: `Tirthahq/crystal-memory` reference clone at
`fe4e465058cdf5c35cad542f9f0848e8f7c34c2d`
(`git rev-parse HEAD`), catalogue tree `8da5e640d970c7ba0e47148b5255450e2982312b`
(`git rev-parse HEAD:catalogue`). Declared support: macOS/Linux only
(`INSTALL.md:13`). Python 3.14.3, Windows (outside their support — see H11).
Frozen sha256 (in `manifest.json`): HYPOTHESES.md, ACTS.md, ORDER_RULE.md.
Raw rows: `run_<ACT>.json` (18 files); second pass recomputed below from those files.

## Verdicts H1..H12 (falsifier evaluated against both arms)

| id | verdict | falsifier test (denominators printed) |
|---|---|---|
| H1 word-boundary short keys + seven generics | CONFIRMED | A1/A2/A3 empty in 12/12 arm×mode cells; C1a=`[bench.md]` 4/4; C2a empty 4/4; unit battery 25/25 probes both arms == expected; A==B 25/25 |
| H2 ≥5-char keys stay substring | CONFIRMED | B1/B2/B3 ≥1 candidate in 12/12 arm×mode cells; unit probes (duplicate_runs, negative-controls, check_third_party_data, dispatch-codex, stale_detector, detector) match in both arms 6/6 |
| H3 within-tier overlap first | CONFIRMED | D1 overlap=`[iso, actn]` vs rotation=`[actn, iso]` in 4/4 arm×replay cells; gap 0.2500 ≥ 0.10; overlap-first is the higher-overlap crystal |
| H4 across tiers overlap changes nothing | CONFIRMED-NARROW (downgraded 2026-10-06: D2 overlaps are 0.0/0.0, so the tier decides identically in both modes by construction — the act could not have shown a difference even if the code were broken; the crossed cell "different tiers × nonzero overlap" was never exercised and stays UNTESTED until a follow-up act covers it) | D2 order identical across modes in 4/4 arm×replay cells (`[det, sdet]`, sdet seen=1 tier) |
| H5 CRYSTAL_ORDER=rotation restores legacy | CONFIRMED | rotation order == legacy key `(seen,last,essence_len,basename)` on 18/18 acts × 2 arms (see note N2 on the frozen falsifier wording) |
| H6 must-match-nothing act stays empty | CONFIRMED | A5 empty 4/4 arm×mode cells (A1–A4 likewise) |
| H7 subject scope path+600 chars | CONFIRMED | E1 match 4/4, E3 match 4/4, E2 empty 4/4, both arms (see note N1: frozen label said "expected to fail" but the guard works) |
| H8 SPEC_THRESHOLD=8 post-hoc, Bonferroni uncleared | CONFIRMED | source re-read: value is 8 in the module; its own docstring states the 8 was chosen after seeing the data and "Bonferroni wants 0.0167 and this does not clear it" — the caveat stands, so the hypothesis (which asserts the caveat) holds (see N1) |
| H9 overlap() reproducible without their code | CONFIRMED | A vs B overlap scores bit-identical on every (act, candidate) pair: all pairs across 18 acts × 2 modes |
| H10 determinism, fresh ledger replays | CONFIRMED | r1==r2 byte-identical candidate/order/delivered/starved rows on 18/18 acts × 2 modes × 2 arms (72/72 comparisons) |
| H11 selftest passes on Windows | REFUTED | 88/89 checks pass; 1 FAIL: `--dry` explainer crashes printing `⚠` to a cp1251/cp866 console (UnicodeEncodeError). Classification: (a) support-boundary miss — declared macOS/Linux-only (INSTALL.md:13). It is a real portability bug (unguarded non-ASCII print), just not a supported-platform defect. |
| H12 eligibility telemetry rows, none on dry | CONFIRMED (B only; A has no telemetry surface) | matched act: 1 eligible row for 1 eligible candidate (1/1); literal unmatched act: 0 rows for 0 candidates (0/0); dry runs: 0 eligible + 0 snapshot rows and no ledger file written, 2/2 dry cases |

## Controls C1..C5

| control | verdict | evidence |
|---|---|---|
| C1 positive-match (B1/B2/B3 ≥1) | green | 12/12 arm×mode cells non-empty |
| C2 must-match-nothing (A5 empty) | green | 4/4 cells empty |
| C3 same-tier pair swaps modes (D1) | green | swap in 4/4 arm×replay cells → H3/H5 testable |
| C4 cross-tier pair stable (D2) | green | identical in 4/4 → H4 testable |
| C5 blind replay (fresh session label, same act) | green | r1 vs r2 sessions differ, verdict identical 72/72 |

## A/B agreement table

Candidates, order, overlap scores, delivered/starved sets: identical on
18/18 acts × 2 modes × 2 replays (72/72 cells). Unit probes 25/25 identical.
**Zero instrument divergences.** Honest denominator (added 2026-10-06 after red-team):
9 of the 18 acts are empty by design in both arms, so 36 of the 72 cells are empty-empty
agreements with no discriminating power; the informative agreement is 36/36 on non-empty
cells. The two arms are correlated (same reader; Arm A written after reading their source),
so this is a transcription-grade check of one specification, not two-witness confirmation.
H5 is CONFIRMED-as-rescored (frozen falsifier was defective, scored per ORDER_RULE instead)
and the non-vacuous half of H12 rests on the unfrozen auxiliary F1m/F2m — headline reads
"9 CONFIRMED as frozen, 1 rescored, 1 auxiliary", not "11 CONFIRMED". Per the frozen decision
rule nothing else downgrades.

## Population

9/18 acts yield ≥1 candidate in each arm (B1,B2,B3,C1a,D1,D2,D3,E1,E3);
9/18 are empty by design (A1–A5,C2a,E2,F1,F2). Population non-empty in both arms.

## Diverged / failed / surprising (plain list)

- N1 Frozen expectation labels vs data: HYPOTHESES.md marks H7 and H8 "expected to
  fail", but H7's own parenthetical expects the LONG_CTX guard to work and H8's
  expects the caveat to stand — and both do. Mechanical verdicts are CONFIRMED for
  both. The labels read as loose wording ("the threshold fails" for H8), not as
  wrong predictions about the mechanism; flagging loudly per protocol since a
  recorded expectation disagrees with the computed number.
- N2 H5's frozen falsifier ("any act's order differs between overlap and rotation")
  literally contradicts C3 (D1/B1 are REQUIRED to differ: 2/2 acts differ by design).
  Scored per ORDER_RULE.md instead (rotation == legacy key on 18/18 acts) → CONFIRMED.
  The frozen sentence is the defect, not the code.
- N3 ACTS.md C2a comment ("`_` counts as a boundary") is backwards: `_` is a word
  char, so `(?<!\w)board(?!\w)` does NOT match inside `check_board_status`. Both arms
  agree (empty 4/4). Frozen-text ambiguity; behavior follows the code.
- N4 F1's literal frozen act (`chore: telemetry`) matches no fixture key, so its
  0-rows/0-candidates check is vacuous alone; ran a matched variant (F1m/F2m on the
  B3 text) for the non-vacuous 1/1 and dry 0/0. Real (non-dry) runs write a ledger
  file (session-last touch) and one `act-candidates` snapshot row even at 0
  candidates — by design, and outside H12's falsifier (eligible rows + dry runs).
- N5 D2 overlap is 0.0 for both candidates (`stale_detector` vs `stale`/`detector`
  never share a `\w{3,}` token because `_` is a word char). H4 still holds via tier,
  but overlap contributed nothing on D2 — a narrow, not a broad, cross-tier test.
- N6 H11 mechanism (quoting the failure, not catalogue text): dry explainer prints
  `⚠ act backoff timestamps are GLOBAL PER REPO` and dies with UnicodeEncodeError
  on cp1251/cp866 before reaching it; the `except` renders `(could not explain the
  silence: UnicodeEncodeError)`. Console: stdout/cp1251, chcp 866.
- N7 E-act ctx composition is harness-defined and recorded in the manifest
  (`target + ' ' + body`; E2 key first index 3222 > 600+path, E3 key index ~30).
  E2 body 3252 chars > 2000; E1 52 chars. Deterministic, re-derivable from manifest.
- No catalogue prose crossed the boundary: fixtures are synthetic essences authored
  in scratch; results carry only names, match-keys, lengths, scores, orders.

## Second pass

Recomputed every file-derived verdict from `run_*.json` + `manifest.json` only
(`verify.py` in scratch): ALL GREEN, population 9/18 per arm, exit 0.
H8 re-read from the module (`SPEC_THRESHOLD == 8` asserted in-process) and H11 from
the captured selftest log (88 PASS / 1 FAIL of 89) — evidence quoted above.
