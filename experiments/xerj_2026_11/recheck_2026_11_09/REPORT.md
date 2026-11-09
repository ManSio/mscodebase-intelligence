# XERJ E1 re-check — 2026-11-09

The XERJ report (2026-11-08) measured `investigate` against plain grep on 24
frozen tasks and concluded **B=0.522 < A=0.667**. That run was invalid as a
product measure: 11 of 24 B answers carried `degraded: grep:timeout`, because
the grep channel walked the tree once per identifier and the measurement stand
held the PID lock. One answer was a hard timeout (23/24 valid).

This re-check runs the **same frozen tasks and the same scoring** after the
2026-11-09 fixes (one-walk grep, parallel test prediction, rerank off by
default, name channel, non-code demotion). The original `baseline.json` /
`baseline_raw.txt` were backed up here and restored byte-identically after the
run (sha256 prefixes `bba6c62991b4` / `05d550ab9c4b`).

Command: `python experiments/xerj_2026_11/run_baseline.py` (N=1, 24 tasks),
then `rescore.py` rules from the raw `b_text`.

## Results

| bucket | 2026-11-08 A | 2026-11-08 B | 2026-11-09 A | 2026-11-09 B |
|---|---:|---:|---:|---:|
| positive (16) | 0.625 | **0.438** | 0.625 | **0.625** |
| ambiguity (4) | 0.500 | 0.667 (3 valid) | 0.500 | 0.500 (4 valid) |
| negative (4) | 1.000 | 0.750 | 1.000 | 0.750 |
| **overall** | 0.667 | **0.522** | 0.667 | **0.625** |
| valid B answers | — | 23/24 | — | **24/24** |
| `grep:timeout` degraded | — | 11/24 | — | **0/24** |

## Reading

- The measurement defect is gone: **24/24 valid answers, zero channel
  timeouts** (was 23/24 with 11 degraded).
- Positive tasks improved by **+18.7 pp** and now equal grep (0.625 vs 0.625).
- Overall gap shrank from **-14.5 pp to -4.2 pp** (0.522 → 0.625 against 0.667).
- Ambiguity is the one bucket that looks worse: 0.667 → 0.500. The old 0.667
  was computed over 3 valid answers (one was invalid), so the two are not
  directly comparable; on a complete panel `investigate` got one of four
  ambiguity tasks and grep got none.
- Negative stays 0.750: N03 still invents `check_knowledge.py` on a key that
  does not exist. This is a real false positive, not a measurement artefact.

**Verdict:** the 2026-11-08 statement “investigate is worse than grep” was
measured on a broken channel and is superseded. After the fix the tool is
**on par with grep on positives and 4.2 pp behind overall**; it still does not
beat grep, and the N03 false positive remains open. Claiming “investigate wins”
would be unsupported.

## Files

- `baseline_2026-11-08.json`, `baseline_raw_2026-11-08.txt` — the original XERJ
  run, restored to `../` after this re-check.
- `baseline_2026-11-09.json`, `baseline_raw_2026-11-09.txt` — this run.
- `run_2026-11-09.log` — raw harness output (summary + per-task misses).
