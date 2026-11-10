# Rewrite gate — frozen expectations for the three-arm experiment

Date: 2026-11-10. Arms differ only in `MSCODEBASE_ASK_REWRITE`:

- `on` (shipped default): Cyrillic question without a code token → ask to rewrite.
- `off`: neighbours returned with a verdict.
- `smart` (candidate): ask to rewrite only when the question also names a
  proper-noun-like Latin word (`Corpus`, `Hub`) — the XERJ N03 shape. Acronyms
  (`LSP`) and dotted tokens (`progress.json`) do not count.

Panel: XERJ 24 + the 3 `mcp_audit` RU questions (27 asks), same index, one
process, interleaved arms, one run each.

Predictions (frozen before the run):

| # | Prediction | Expected | Falsifier |
|---|---|---|---|
| R1 | `smart` gates exactly one query (N03) | PASS | any other task returns `ask_rewrite` |
| R2 | `smart` keeps N03 at zero rows | PASS | any `file:line` row in N03 |
| R3 | `smart` loses no hit vs `off` (top1 and any) | PASS | any task's top1/any drops |
| R4 | `smart` restores P16 (top1 True, rows present) | PASS | P16 still `ask_rewrite` or top1 False |
| R5 | RU questions are un-gated in `smart` and still miss the gold | **FAIL** | any RU `any` becomes True (we predict retrieval, not the gate, is the limit) |

Kill: R3 or R2 fails → do not ship `smart`; keep `on`.

Rationale: `on` buys N03 and costs P16 (measured earlier). `smart` should keep
the N03 property while returning the P16 neighbours, which is strictly better
if R1-R4 hold. The rule must not be tuned after seeing the numbers.
