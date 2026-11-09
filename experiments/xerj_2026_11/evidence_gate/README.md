# Evidence gate — control vs treatment

`investigate` now verifies its own rows before showing them: a definition must
be a declaration at that line, a path must exist, a stale file is named as
stale, and the answer carries a deterministic verdict with a confidence score.
The mechanism is documented in `docs/{en,ru,zh}/SEARCH_PIPELINE.md` §5.1.

This folder is the measurement, not the sales pitch.

## Reproduce

```bash
python experiments/xerj_2026_11/evidence_gate/run_gate.py
```

One process, one index, one commit. The only difference between the arms is the
environment flag:

- `MSCODEBASE_EVIDENCE_GATE=0` — control (the same commit with the gate off;
  the rewrite fixes are not behind this flag and apply to both arms);
- `MSCODEBASE_EVIDENCE_GATE=1` — treatment (gate + verified-definition promotion).

The arms are interleaved per task, so a background writer or a cold index
affects both arms instead of one sweep (see the module docstring).

## Files

| File | What it is |
|---|---|
| `frozen/HYPOTHESES.md` | predictions and kill criteria, written before the first run |
| `frozen/MANIFEST.sha256` | sha256 of the two frozen task files |
| `run_gate.py` | the harness (metrics defined inside, not copied) |
| `results_control.json` / `results_treatment.json` | one row per task per run (3 runs per task), with the raw answer |
| `summary_*.json` | aggregated metrics |
| `determinism.json` | every task rerun 3 times in the treatment arm |
| `REPORT.md` | numbers, verdict on each prediction, threats to validity |

## Panels

- XERJ 24: 16 positive, 4 ambiguity (both golds required), 4 negative (no
  answer exists; any `file:line` row is a false positive).
- `mcp_audit` 17: 6 English + 3 Russian questions on this repo, 4 on `black`,
  4 on `httpbin`.

The panels are frozen: a rule that only works on them is not a rule, which is
why the report separates "confirmed on the panel" from "held-out".
