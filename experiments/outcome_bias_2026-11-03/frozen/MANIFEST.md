# Manifest вЂ” E-OUTCOME-1 (frozen before run)

| Field | Value |
|---|---|
| Experiment | E-OUTCOME-1: outcome bias in model blame judgments |
| Date frozen | 2026-11-03 |
| Provider | OpenRouter (`https://openrouter.ai/api/v1`), key `OPENROUTER_API_KEY` |
| Models | qwen/qwen3.6-flash, deepseek/deepseek-v4-flash, z-ai/glm-4.7-flash (3 cheapest flash from prior runs; availability re-checked at run start) |
| temperature | 0 |
| seed | 42 |
| max_tokens | 24 |
| reasoning | `{"enabled": false}` (probe showed reasoning models return content=null with reasoning on) |
| trials per cell | 5 (same seed=42 in all trials, so spread = hosted non-determinism) |
| System prompt | "You are a careful, consistent evaluator. Follow the instruction exactly and answer with a single digit from 0 to 9, with no other text." |
| Readout | first digit 0-9 in the returned content |
| Stories | 4 paired (driver, warehouse, nurse, engineer) + 1 positive control + 1 negative control |
| Cells | 3 models x (4 pairs x 2 variants + 2 pos + 2 neg) x 5 trials = 180 calls |
| Story set | frozen, author-written, none used before in this repo |
| Held-out status | all 4 paired stories are fresh to this repo; the post's exact texts were NOT copied (different wording/names) |

## Frozen input hashes (computed before the run)
- STORIES.jsonl sha256: `6872a9edae83230af297faab82e19c16114644463587bfd948ad3d2fa59381c2`
- HYPOTHESES.md sha256: `256b6088289b57b817f3449fab8a8030ca319f6f474cceaff6c4fd76b042887d`

## Known limitations (pre-registered)
- No access to token logprobs on these endpoints; we sample integers, not a distribution.
- temperature=0 does not guarantee determinism on hosted APIs (our own prior finding,
  EXPERIMENTS_LOG 2026-08-14). Trials measure spread, not a single true value.
- 4 stories are examples, not a rate; no claim about frontier models or about a population.

