# Manifest — E-OUTCOME-2 (frozen before run)

| Field | Value |
|---|---|
| Experiment | E-OUTCOME-2: finer readout replication of E-OUTCOME-1 |
| Date frozen | 2026-11-03 |
| Provider | OpenRouter |
| Models | qwen/qwen3.6-flash, deepseek/deepseek-v4-flash, z-ai/glm-4.7-flash |
| temperature / seed | 0 / 42 (same seed all trials) |
| max_tokens | 24 |
| reasoning | disabled |
| readout | first integer 0-100 |
| trials per cell | 5 |
| Stories | identical to E1 (`frozen/STORIES.jsonl`, sha256 6872a9ed…) — not edited after E1 |
| Cells | 3 models x 12 cases x 5 trials = 180 calls |
| Difference from E1 | scale only (0-9 -> 0-100) |

## Why not logprobs
Probed 2026-11-03: qwen rejects top_logprobs>5 (HTTP 400), deepseek and glm return
`logprobs: null`. The post's probability-over-digits method is not available on this
harness, so the finer integer scale is the available substitute.
