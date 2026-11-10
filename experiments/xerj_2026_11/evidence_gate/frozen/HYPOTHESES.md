# Evidence gate — frozen expectations (written BEFORE the first run)

Date: 2026-11-10. Panel: XERJ frozen 24 (positive 16, ambiguity 4, negative 4) +
`mcp_audit/questions.json` 17 (mscodebase 6 en + 3 ru, black 4, httpbin 4).

Arms (same commit, same process, same index, only one env flag differs):

- **control** `MSCODEBASE_EVIDENCE_GATE=0` — the same commit with the gate off
  (the rewrite-gate fixes are not behind this flag and apply to both arms).
- **treatment** `MSCODEBASE_EVIDENCE_GATE=1` — evidence gate + verified-definition
  promotion.

Metrics (fixed now, not after seeing numbers):

- `top1` — first `file:line` row's file matches a gold file (substring rule used by
  `run_baseline.score`).
- `any@8` — any of the top-8 rows matches a gold file.
- `ambiguity` — EVERY gold file appears in the top-8.
- `negative` — no `file:line` row at all (frozen rule); `answered` reports whether the
  answer shows `exact: <subject>=0`.
- `valid` — the tool answered (no error envelope, no timeout).
- `latency` — wall clock of `investigate`, mean and p95.

Predictions (wording as frozen before the run; the Falsifier column was added
later to satisfy §19.1 and does not change the predictions):

| # | Prediction | Expected | Falsifier |
|---|---|---|---|
| H1 | `any@8` does not drop on any bucket: the gate annotates and only stable-promotes rows that already exist. | PASS | any bucket loses a task |
| H2 | `negative` does not change; the gate never adds rows. | PASS | a negative task gains a row |
| H3 | `top1` improves on mcp_audit where a verified declaration already existed below rank 1 (expected +0..1 of 17). No change on XERJ positive is acceptable. Keep if `>=` control, kill if `-1`. | PASS | mcp_audit top1 drops, or any bucket loses top1 |
| H4 | `ambiguity` unchanged (promotion is stable and keeps both declarations). | PASS | a task loses a gold |
| H5 | latency `mean <= control + 0.25 s`, `p95 <= control + 0.60 s` (8 file reads + ast parse per answer). | PASS | mean or p95 above the budget |
| H6 | determinism: two treatment runs on 4 fixed tasks give the same verdict and the same first row. | PASS | two repeats differ |
| H7 | the gate raises recall (`any@8` rises). | **FAIL** | no bucket rises — expected: the gate annotates, it does not retrieve |
| H8 | verification changes the held-out external results. | **FAIL** | no changed task on itsdangerous/iniconfig — expected |

H7 and H8 are the two hypotheses registered as expected to fail (§19.1). They are
not kill criteria: they are predictions that a verification layer must NOT turn
into a retrieval claim (H7) and must NOT disturb a corpus it never saw (H8).
Their measured outcome is in `REPORT.md`.

If a kill criterion fires, the gate is not shipped as-is: fix the rule, keep the
measurement, do not edit the panel.

Inputs are read-only; `MANIFEST.sha256` pins the task files.
