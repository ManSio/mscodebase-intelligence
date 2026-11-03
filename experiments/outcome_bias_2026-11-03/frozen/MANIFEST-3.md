# Manifest вЂ” E-OUTCOME-3 (local, frozen before run)

| Field | Value |
|---|---|
| Experiment | E-OUTCOME-3: local small instruct model replication |
| Date frozen | 2026-11-03 |
| Endpoint | `http://localhost:1234/v1/chat/completions` (LM Studio, OpenAI-compatible) |
| Auth | none |
| Model | `qwen2.5-3b-instruct` |
| temperature / seed | 0 / 42 (same seed all trials) |
| max_tokens | 16 |
| reasoning param | not sent |
| timeout | 300 s/call |
| readout | first digit 0-9 |
| trials per cell | 5 |
| Stories | identical to E1 (`frozen/STORIES.jsonl`) |
| Cells | 1 model x 12 cases x 5 trials = 60 calls |
| System prompt | scale-aware (fixed after the E2 bug: E2 sent "0-9" even on a 0-100 prompt) |
| Estimated cost | 0 (local) |

## Frozen hashes (computed BEFORE the run)
- STORIES.jsonl sha256: `6872a9edae83230af297faab82e19c16114644463587bfd948ad3d2fa59381c2`
- HYPOTHESES-3.md sha256: `fd048fdd1957983f26d1f1801c333732ed6155bb9fd60cd2fe35929c441ff2c5`
- MANIFEST-3.md sha256 (self-reference impossible; recorded after writing, before run): `a996f70c18d0c5db40bf97baf416f7b77dc6694c814bd66fd665bc78e8e7d634`

