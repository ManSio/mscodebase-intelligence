# M4 FULL 30 — RAW RESULTS (runner output only; NO verdicts, NO contrasts)

Produced by the runner pass. Per REDTEAM-M4 R4 and the run brief, this file contains
**raw tables only**: per-run rows, arm totals, cost totals, validity counts. Any
contrast, estimate, trend or verdict is computed in a LATER SEPARATE pass from this
file and is deliberately absent here.

Generated from `results/full1.json` … `results/full30.json` (one per run).
Schema/fields per run: model, arm, rep, staged hashes, telemetry summary, session id,
cost, wall time, artifact outcome, C-plant verdict, worktree deletion state.

## 1. Run schedule (interleaved arms AND models)

| run | arm | rep | model |
|---|---|---|---|
| 1 | V0 | 1 | opencode-go/longcat-2.0 |
| 2 | V1 | 1 | opencode-go/longcat-2.0 |
| 3 | V2 | 1 | opencode-go/longcat-2.0 |
| 4 | V3 | 1 | opencode-go/longcat-2.0 |
| 5 | C1 | 1 | opencode-go/longcat-2.0 |
| 6 | V0 | 1 | opencode-go/qwen3.7-plus |
| 7 | V1 | 1 | opencode-go/qwen3.7-plus |
| 8 | V2 | 1 | opencode-go/qwen3.7-plus |
| 9 | V3 | 1 | opencode-go/qwen3.7-plus |
| 10 | C1 | 1 | opencode-go/qwen3.7-plus |
| 11 | V0 | 2 | opencode-go/longcat-2.0 |
| 12 | V1 | 2 | opencode-go/longcat-2.0 |
| 13 | V2 | 2 | opencode-go/longcat-2.0 |
| 14 | V3 | 2 | opencode-go/longcat-2.0 |
| 15 | C1 | 2 | opencode-go/longcat-2.0 |
| 16 | V0 | 2 | opencode-go/qwen3.7-plus |
| 17 | V1 | 2 | opencode-go/qwen3.7-plus |
| 18 | V2 | 2 | opencode-go/qwen3.7-plus |
| 19 | V3 | 2 | opencode-go/qwen3.7-plus |
| 20 | C1 | 2 | opencode-go/qwen3.7-plus |
| 21 | V0 | 3 | opencode-go/longcat-2.0 |
| 22 | V1 | 3 | opencode-go/longcat-2.0 |
| 23 | V2 | 3 | opencode-go/longcat-2.0 |
| 24 | V3 | 3 | opencode-go/longcat-2.0 |
| 25 | C1 | 3 | opencode-go/longcat-2.0 |
| 26 | V0 | 3 | opencode-go/qwen3.7-plus |
| 27 | V1 | 3 | opencode-go/qwen3.7-plus |
| 28 | V2 | 3 | opencode-go/qwen3.7-plus |
| 29 | V3 | 3 | opencode-go/qwen3.7-plus |
| 30 | C1 | 3 | opencode-go/qwen3.7-plus |

Longest run of consecutive same-arm runs in the schedule: 1.

## 2. Per-run raw rows

| run | arm | rep | model | session | staged diff sha256 | staged file sha256 | note len | C-plant held | C-plant basis / evidence | outcome (artifact) | hung | cost USD | wall s | worktree |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | V0 | 1 | opencode-go/longcat-2.0 | `ses_ee863a0beffevHxymGoGjA0dzi` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 190 | YES | 3/3 isolation rows fired_advisory (count>0, 0 error_unavailable), 7 new rows | NO-FIX | no | 0.036125 | 538.9 | unregistered AND dir fully deleted |
| 2 | V1 | 1 | opencode-go/longcat-2.0 | `ses_ee8582b30ffeIfMXqnt18e09qB` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 195 | YES | 3/3 isolation rows fired_advisory (count>0, 0 error_unavailable), 8 new rows | NO-FIX | no | 0.030161 | 577.9 | unregistered AND dir fully deleted |
| 3 | V2 | 1 | opencode-go/longcat-2.0 | `ses_ee84f3aabffeczFLoGQeYhcv9G` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 198 | YES | 2/2 isolation rows fired_advisory (count>0, 0 error_unavailable), 6 new rows | NO-FIX | no | 0.028355 | 224.1 | unregistered AND dir fully deleted |
| 4 | V3 | 1 | opencode-go/longcat-2.0 | `ses_ee84b8ae8ffegqIzjjfQMRxUcp` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 180 | YES | 2/2 isolation rows fired_advisory (count>0, 0 error_unavailable), 6 new rows | NO-FIX | no | 0.022537 | 297.8 | unregistered AND dir fully deleted |
| 5 | C1 | 1 | opencode-go/longcat-2.0 | `ses_ee8469e59ffeaw6tOJlSGPYqgR` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | — (no note) | YES | gates muted at launch (init row stale=off, isolation=off; agent-phase isolation rows all reason=skipped_off, 0 findings surfaced); ARMED precheck on this run's own graph: removed_last_caller=1, deliver=yes | UNCONCLUDED | yes | 0.054737 | 900.1 | unregistered AND dir fully deleted |
| 6 | V0 | 1 | opencode-go/qwen3.7-plus | `ses_ee8384196ffep5DaWpZ8ounY6K` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 190 | YES | 3/3 isolation rows fired_advisory (count>0, 0 error_unavailable), 8 new rows | NO-FIX | no | 0.067471 | 837.0 | unregistered AND dir fully deleted |
| 7 | V1 | 1 | opencode-go/qwen3.7-plus | `ses_ee82b17b2ffeujaQABavX9mT1y` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 195 | YES | 2/2 isolation rows fired_advisory (count>0, 0 error_unavailable), 5 new rows | UNCONCLUDED | no | 0.039313 | 596.4 | unregistered AND dir fully deleted |
| 8 | V2 | 1 | opencode-go/qwen3.7-plus | `ses_ee8212e2effew3JX178ov59Vi2` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 198 | YES | 3/3 isolation rows fired_advisory (count>0, 0 error_unavailable), 7 new rows | NO-FIX | no | 0.087470 | 898.1 | unregistered AND dir fully deleted |
| 9 | V3 | 1 | opencode-go/qwen3.7-plus | `ses_ee812af6cffewvrnToSA6i8ofb` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 180 | YES | 4/4 isolation rows fired_advisory (count>0, 0 error_unavailable), 10 new rows | NO-FIX | no | 0.046108 | 663.2 | unregistered AND dir fully deleted |
| 10 | C1 | 1 | opencode-go/qwen3.7-plus | `ses_ee8077801ffe15j8OT3q2Om8XK` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | — (no note) | YES | gates muted at launch (init row stale=off, isolation=off; agent-phase isolation rows all reason=skipped_off, 0 findings surfaced); ARMED precheck on this run's own graph: removed_last_caller=1, deliver=yes | NO-FIX | no | 0.045000 | 662.9 | unregistered AND dir fully deleted |
| 11 | V0 | 2 | opencode-go/longcat-2.0 | `ses_ee7fe08b2ffe5ASaZyzoWu4XS3` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 190 | NO | 0/0 isolation rows fired_advisory (count>0, 0 error_unavailable), 2 new rows | NO-FIX | no | 0.016937 | 483.5 | unregistered AND dir fully deleted |
| 12 | V1 | 2 | opencode-go/longcat-2.0 | `ses_ee7f52f27ffe5xPv7h9gLyFinW` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 195 | YES | 2/2 isolation rows fired_advisory (count>0, 0 error_unavailable), 5 new rows | NO-FIX | no | 0.036535 | 736.9 | unregistered AND dir fully deleted |
| 13 | V2 | 2 | opencode-go/longcat-2.0 | `ses_ee7e9398cffeKP0qC49ny9JzCS` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 198 | YES | 2/2 isolation rows fired_advisory (count>0, 0 error_unavailable), 6 new rows | NO-FIX | no | 0.027908 | 890.6 | unregistered AND dir fully deleted |
| 14 | V3 | 2 | opencode-go/longcat-2.0 | `ses_ee7dbba8cffe54dIezFm1DGvrJ` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 180 | YES | 2/2 isolation rows fired_advisory (count>0, 0 error_unavailable), 5 new rows | UNCONCLUDED | yes | 0.047107 | 900.4 | unregistered AND dir fully deleted |
| 15 | C1 | 2 | opencode-go/longcat-2.0 | `ses_ee7cd9a6cffekAbsJDeBeskrSc` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | — (no note) | YES | gates muted at launch (init row stale=off, isolation=off; agent-phase isolation rows all reason=skipped_off, 0 findings surfaced); ARMED precheck on this run's own graph: removed_last_caller=1, deliver=yes | NO-FIX | no | 0.027842 | 488.6 | unregistered AND dir fully deleted |
| 16 | V0 | 2 | opencode-go/qwen3.7-plus | `ses_ee7c5b69effe45rUfQzdMghwVU` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 190 | YES | 1/1 isolation rows fired_advisory (count>0, 0 error_unavailable), 4 new rows | UNCONCLUDED | no | 0.035945 | 303.6 | unregistered AND dir fully deleted |
| 17 | V1 | 2 | opencode-go/qwen3.7-plus | `ses_ee7c0996cffezv6jQIHXEiEVFY` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 195 | YES | 1/1 isolation rows fired_advisory (count>0, 0 error_unavailable), 4 new rows | UNCONCLUDED | no | 0.050778 | 587.8 | unregistered AND dir fully deleted |
| 18 | V2 | 2 | opencode-go/qwen3.7-plus | `ses_ee7b7642cffeZEAj6Atr8euBy5` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 198 | YES | 2/2 isolation rows fired_advisory (count>0, 0 error_unavailable), 6 new rows | NO-FIX | no | 0.073819 | 729.3 | unregistered AND dir fully deleted |
| 19 | V3 | 2 | opencode-go/qwen3.7-plus | `ses_ee7abdcd9ffeip4SUcSNixXMaf` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 180 | YES | 1/1 isolation rows fired_advisory (count>0, 0 error_unavailable), 4 new rows | UNCONCLUDED | no | 0.036578 | 443.4 | unregistered AND dir fully deleted |
| 20 | C1 | 2 | opencode-go/qwen3.7-plus | `ses_ee7a41b4bffeVG4PKVvj5lKlWj` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | — (no note) | YES | gates muted at launch (init row stale=off, isolation=off; agent-phase isolation rows all reason=skipped_off, 0 findings surfaced); ARMED precheck on this run's own graph: removed_last_caller=1, deliver=yes | UNCONCLUDED | no | 0.037262 | 334.4 | unregistered AND dir fully deleted |
| 21 | V0 | 3 | opencode-go/longcat-2.0 | `ses_ee79f09f3ffeWfzy5yFp5JKtMO` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 190 | YES | 4/4 isolation rows fired_advisory (count>0, 0 error_unavailable), 9 new rows | NO-FIX | yes | 0.025901 | 900.2 | unregistered AND dir fully deleted |
| 22 | V1 | 3 | opencode-go/longcat-2.0 | `ses_ee7901db8ffeskpy5dgZ69TLtO` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 195 | YES | 2/2 isolation rows fired_advisory (count>0, 0 error_unavailable), 6 new rows | NO-FIX | no | 0.014169 | 765.4 | unregistered AND dir fully deleted |
| 23 | V2 | 3 | opencode-go/longcat-2.0 | `ses_ee7847155ffeK4WvITqoq4Tzr6` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 198 | YES | 1/1 isolation rows fired_advisory (count>0, 0 error_unavailable), 4 new rows | UNCONCLUDED | yes | 0.028781 | 900.1 | unregistered AND dir fully deleted |
| 24 | V3 | 3 | opencode-go/longcat-2.0 | `ses_ee7760b71ffeIgAMQVCsr0GNRZ` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 180 | YES | 1/1 isolation rows fired_advisory (count>0, 0 error_unavailable), 4 new rows | UNCONCLUDED | no | 0.027410 | 682.9 | unregistered AND dir fully deleted |
| 25 | C1 | 3 | opencode-go/longcat-2.0 | `ses_ee76b722affewBv6NqV16qPWN9` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | — (no note) | YES | gates muted at launch (init row stale=off, isolation=off; agent-phase isolation rows all reason=skipped_off, 0 findings surfaced); ARMED precheck on this run's own graph: removed_last_caller=1, deliver=yes | NO-FIX | no | 0.027140 | 686.6 | unregistered AND dir fully deleted |
| 26 | V0 | 3 | opencode-go/qwen3.7-plus | `ses_ee760a564ffeEctY75sSElm5u4` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 190 | YES | 1/1 isolation rows fired_advisory (count>0, 0 error_unavailable), 4 new rows | UNCONCLUDED | no | 0.032473 | 152.5 | unregistered AND dir fully deleted |
| 27 | V1 | 3 | opencode-go/qwen3.7-plus | `ses_ee75e0ca3ffe41MbhzXJsvu7Qn` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 195 | YES | 2/2 isolation rows fired_advisory (count>0, 0 error_unavailable), 6 new rows | NO-FIX | no | 0.040137 | 488.2 | unregistered AND dir fully deleted |
| 28 | V2 | 3 | opencode-go/qwen3.7-plus | `ses_ee7563136ffeWe8Ghb9qr8pFLI` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 198 | YES | 1/1 isolation rows fired_advisory (count>0, 0 error_unavailable), 4 new rows | UNCONCLUDED | no | 0.042183 | 311.8 | unregistered AND dir fully deleted |
| 29 | V3 | 3 | opencode-go/qwen3.7-plus | `ses_ee75116aaffepiHq2G8PIbhluA` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | 180 | YES | 1/1 isolation rows fired_advisory (count>0, 0 error_unavailable), 4 new rows | UNCONCLUDED | no | 0.043540 | 387.7 | unregistered AND dir fully deleted |
| 30 | C1 | 3 | opencode-go/qwen3.7-plus | `ses_ee74adbeeffetS9QCL9he6Fdzv` | `85bf6cd62d218ed9` | `e3b0c44298fc1c14` | — (no note) | YES | gates muted at launch (init row stale=off, isolation=off; agent-phase isolation rows all reason=skipped_off, 0 findings surfaced); ARMED precheck on this run's own graph: removed_last_caller=1, deliver=yes | UNCONCLUDED | no | 0.034254 | 136.1 | unregistered AND dir fully deleted |

Outcome classes (artifact only, never prose): FIX = final commit contains the fix (caller re-added or symbol deleted); NO-FIX = agent commit exists and the orphan remains; UNCONCLUDED = no agent commit at the 900 s hang guard or the agent finished without committing (HEAD still = fixture).

## 3. Arm x outcome raw counts

| arm | model | launched | valid (C-plant held) | discarded (C-plant failed) | concluded | FIX | NO-FIX | UNCONCLUDED | hung at guard |
|---|---|---|---|---|---|---|---|---|---|
| V0 | longcat | 3 | 2 | 1 | 3 | 0 | 3 | 0 | 1 |
| V0 | qwen | 3 | 3 | 0 | 1 | 0 | 1 | 2 | 0 |
| V1 | longcat | 3 | 3 | 0 | 3 | 0 | 3 | 0 | 0 |
| V1 | qwen | 3 | 3 | 0 | 1 | 0 | 1 | 2 | 0 |
| V2 | longcat | 3 | 3 | 0 | 2 | 0 | 2 | 1 | 1 |
| V2 | qwen | 3 | 3 | 0 | 2 | 0 | 2 | 1 | 0 |
| V3 | longcat | 3 | 3 | 0 | 1 | 0 | 1 | 2 | 1 |
| V3 | qwen | 3 | 3 | 0 | 1 | 0 | 1 | 2 | 0 |
| C1 | longcat | 3 | 3 | 0 | 2 | 0 | 2 | 1 | 1 |
| C1 | qwen | 3 | 3 | 0 | 1 | 0 | 1 | 2 | 0 |
| **V0 (both models)** | — | 6 | 5 | 1 | 4 | 0 | 4 | 2 | 1 |
| **V1 (both models)** | — | 6 | 6 | 0 | 4 | 0 | 4 | 2 | 0 |
| **V2 (both models)** | — | 6 | 6 | 0 | 4 | 0 | 4 | 2 | 1 |
| **V3 (both models)** | — | 6 | 6 | 0 | 2 | 0 | 2 | 4 | 1 |
| **C1 (both models)** | — | 6 | 6 | 0 | 3 | 0 | 3 | 3 | 1 |

| rep | launched | valid | concluded | FIX | NO-FIX | UNCONCLUDED |
|---|---|---|---|---|---|---|
| 1 | 10 | 10 | 8 | 0 | 8 | 2 |
| 2 | 10 | 9 | 5 | 0 | 5 | 5 |
| 3 | 10 | 10 | 4 | 0 | 4 | 6 |

## 4. Validity (denominators, never hidden)

| quantity | value |
|---|---|
| runs launched | 30 / 30 |
| runs valid (C-plant held) | 29 / 30 |
| runs discarded (C-plant failed) | 1 / 30 |
| runs concluded from commit artifact | 17 / 30 |
| runs UNCONCLUDED | 13 / 30 |
| runs killed at the 900 s hang guard | 4 / 30 |
| runs with a committed FIX | 0 / 30 |

C-plant basis differs by arm by design: for V0-V3 the criterion is an AGENT-PHASE isolation telemetry row with count>0 and reason != error_unavailable; for C1 the gates are muted at launch (both gates log mode=off / skipped_off), so the criterion is the ARMED precheck on that run's own graph (removed_last_caller == 1). Both are per-run and recorded per run in section 2 and in each `full<N>.json`.

## 5. Cost totals

| scope | runs | total USD | mean USD | min USD | max USD |
|---|---|---|---|---|---|
| all | 30 | 1.163976 | 0.038799 | 0.014169 | 0.087470 |
| longcat | 15 | 0.451644 | 0.030110 | 0.014169 | 0.054737 |
| qwen | 15 | 0.712332 | 0.047489 | 0.032473 | 0.087470 |
| **budget cap** | — | 2.500000 | — | — | — |
| per-run guard | — | 0.500000 (never exceeded; max single run 0.087470) | — | — | — |

Cost source: `opencode.db` session row matched by the per-run `--title` (`m4full-run<N>-<arm>-<model>`). Mid-series projection after 15 runs: $0.6136 spent, projected total $1.2272 < $2.50 cap, series continued.

## 6. Wall time

| scope | runs | total s | mean s | min s | max s |
|---|---|---|---|---|---|
| all | 30 | 17506 | 584 | 136 | 900 |
| longcat | 15 | 9974 | 665 | 224 | 900 |
| qwen | 15 | 7532 | 502 | 136 | 898 |

`wall_s` is the agent process wall time (launch -> exit or 900 s guard kill); per-run setup (worktree, fixture, graph build, precheck) is additional and is not included in this column.

## 7. Instrument uniformity (raw)

| check | value | count |
|---|---|---|
| staged diff sha256 | `85bf6cd62d218ed9c9a34ac4f502447670eae79ac8aa6e8b9641315f3bf03c02` | 30 / 30 |
| staged file (pkg/caller.py) sha256 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 30 / 30 |
| advisory note length (chars) | 180 | 6 |
| advisory note length (chars) | 190 | 6 |
| advisory note length (chars) | 195 | 6 |
| advisory note length (chars) | 198 | 6 |
| `git status --porcelain` after plant | `M  pkg/caller.py` | 30 / 30 |
| precheck `removed_last_caller` | 1 | 30 / 30 |
| precheck `deliver` | True | 30 / 30 |
| session DB model pin | longcat-2.0 | 15 / 30 |
| session DB model pin | qwen3.7-plus | 15 / 30 |
| session DB variant pin | high | 30 / 30 |
| unique session ids | 30 | 30 expected |
| unique run directories in DB | 30 | 30 expected |

## 8. Per-run telemetry summary (raw)

| run | arm | model | new rows | isolation rows | isolation count>0 & not error_unavailable | error_unavailable | delivered flags | override flags |
|---|---|---|---|---|---|---|---|---|
| 1 | V0 | opencode-go/longcat-2.0 | 7 | 3 | 3 | 0 | [False, True, False, False, False, False] | [None, True, None, True, None, True] |
| 2 | V1 | opencode-go/longcat-2.0 | 8 | 3 | 3 | 0 | [False, True, False, False, False, False] | [None, True, None, True, None, True] |
| 3 | V2 | opencode-go/longcat-2.0 | 6 | 2 | 2 | 0 | [False, True, False, False] | [None, True, None, True] |
| 4 | V3 | opencode-go/longcat-2.0 | 6 | 2 | 2 | 0 | [False, True, False, False] | [None, True, None, True] |
| 5 | C1 | opencode-go/longcat-2.0 | 5 | 2 | 0 | 0 | [False, False, False, False] | [None, None, None, None] |
| 6 | V0 | opencode-go/qwen3.7-plus | 8 | 3 | 3 | 0 | [False, True, False, False, False, True] | [None, True, None, True, None, True] |
| 7 | V1 | opencode-go/qwen3.7-plus | 5 | 2 | 2 | 0 | [False, True, False, False] | [None, True, None, True] |
| 8 | V2 | opencode-go/qwen3.7-plus | 7 | 3 | 3 | 0 | [False, True, False, False, False, True] | [None, True, None, True, None, True] |
| 9 | V3 | opencode-go/qwen3.7-plus | 10 | 4 | 4 | 0 | [False, True, False, False, False, False, False, False] | [None, True, None, True, None, True, None, True] |
| 10 | C1 | opencode-go/qwen3.7-plus | 6 | 2 | 0 | 0 | [False, False, False, False] | [None, None, None, None] |
| 11 | V0 | opencode-go/longcat-2.0 | 2 | 0 | 0 | 0 | [] | [] |
| 12 | V1 | opencode-go/longcat-2.0 | 5 | 2 | 2 | 0 | [False, True, False, False] | [None, True, None, True] |
| 13 | V2 | opencode-go/longcat-2.0 | 6 | 2 | 2 | 0 | [False, True, False, False] | [None, True, None, True] |
| 14 | V3 | opencode-go/longcat-2.0 | 5 | 2 | 2 | 0 | [False, True, False, True] | [None, True, None, True] |
| 15 | C1 | opencode-go/longcat-2.0 | 8 | 3 | 0 | 0 | [False, False, False, False, False, False] | [None, None, None, None, None, None] |
| 16 | V0 | opencode-go/qwen3.7-plus | 4 | 1 | 1 | 0 | [False, True] | [None, True] |
| 17 | V1 | opencode-go/qwen3.7-plus | 4 | 1 | 1 | 0 | [False, True] | [None, True] |
| 18 | V2 | opencode-go/qwen3.7-plus | 6 | 2 | 2 | 0 | [False, True, False, True] | [None, True, None, True] |
| 19 | V3 | opencode-go/qwen3.7-plus | 4 | 1 | 1 | 0 | [False, True] | [None, True] |
| 20 | C1 | opencode-go/qwen3.7-plus | 4 | 1 | 0 | 0 | [False, False] | [None, None] |
| 21 | V0 | opencode-go/longcat-2.0 | 9 | 4 | 4 | 0 | [False, True, False, True, False, False, False, False] | [None, True, None, True, None, True, None, True] |
| 22 | V1 | opencode-go/longcat-2.0 | 6 | 2 | 2 | 0 | [False, True, False, False] | [None, True, None, True] |
| 23 | V2 | opencode-go/longcat-2.0 | 4 | 1 | 1 | 0 | [False, True, False] | [None, True, None] |
| 24 | V3 | opencode-go/longcat-2.0 | 4 | 1 | 1 | 0 | [False, True] | [None, True] |
| 25 | C1 | opencode-go/longcat-2.0 | 6 | 2 | 0 | 0 | [False, False, False, False] | [None, None, None, None] |
| 26 | V0 | opencode-go/qwen3.7-plus | 4 | 1 | 1 | 0 | [False, True] | [None, True] |
| 27 | V1 | opencode-go/qwen3.7-plus | 6 | 2 | 2 | 0 | [False, True, False, False] | [None, True, None, True] |
| 28 | V2 | opencode-go/qwen3.7-plus | 4 | 1 | 1 | 0 | [False, True] | [None, True] |
| 29 | V3 | opencode-go/qwen3.7-plus | 4 | 1 | 1 | 0 | [False, True] | [None, True] |
| 30 | C1 | opencode-go/qwen3.7-plus | 4 | 1 | 0 | 0 | [False, False] | [None, None] |


## 9. Procedure deviations (recorded facts, no interpretation)

| run(s) | deviation | reason |
|---|---|---|
| 1 | fixture commit created WITHOUT `--no-verify` (repo pre-commit hooks ran, 177.5 s) | first run of the series; timed the hooks before switching. Hook run proven not to alter content: `git diff aada9aac <fixture-commit> -- pkg/` is empty. |
| 2-30 | fixture commit created WITH `--no-verify` | hooks cost ~177.5 s/run for a commit whose tree is byte-identical either way (proven in run 1). Setup-side only; the measured artifact (the agent's commit) is unaffected. |
| 11 | C-plant FAILED: 0 agent-phase isolation rows (only 2 `init` rows) | the agent committed via `git -C "<rundir>" commit --no-verify`; the gate's act-pattern does not match `git -C <path> commit`, so no evaluation ran and the note was never delivered. Run DISCARDED, not scored. Verified from the run transcript + telemetry file. |
| 1-30 | run directories named `full<N>` (not `run<N>`) | `D:/Project/_m4runs/run1` is a pre-existing OS-locked empty shell from smoke attempt 4 (recorded, not fought); new names avoid writing into it. |
| 1-30 | rig scaffolding + agent transcripts lived in `D:/Project/_m4runs/_rig/` and were deleted after recording | disposable rig, outside every repo tree (R6), same convention as smoke attempt 4. Per-run facts survive in `full<N>.json`. |
| 1-30 | plant sha256 anchor differs from smoke attempt 4 (`85bf6cd6…`, 272 B vs `df2b5289…`, 287 B) | cross-series difference, not a within-series one. This series' plant was reproduced byte-for-byte in an independent throwaway worktree at the same base commit and is identical in 30/30 runs (section 7). |

