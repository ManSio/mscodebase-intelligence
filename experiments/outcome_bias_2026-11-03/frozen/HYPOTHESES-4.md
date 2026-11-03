# Frozen hypotheses — E-OUTCOME-4 (action sensitivity control)

Frozen BEFORE the first E4 call. Purpose: resolve the ambiguity left by E1-E3.
In all three earlier runs the positive control (mild vs severe action, both ending in harm)
came out flat. Two explanations are possible:
(a) the ruler is broken (scale/saturation), or
(b) the model genuinely weights outcome over action.
E4 separates them by asking the same mild-vs-severe question in the **no-harm** condition.

Stimuli (frozen, `frozen/ACTION_CONTROL.jsonl`):
- mild action: 1-second glance at 15 km/h.
- severe action: 12-second eyes-off-road video at 50 km/h.
- outcome either harm (child hit) or no harm (nothing crossed).

| # | Hypothesis | Falsifier | Expected |
|---|---|---|---|
| H1 | With no harm, severe action gets higher blame than mild by > 1.0 | gap <= 1.0 | PASS expected if the model reads action at all |
| H2 | With harm, severe and mild are within 1.0 of each other | gap > 1.0 | **FAIL expected** (outcome dominance / ceiling) |
| H3 | Removing the outcome moves blame more than worsening the action | outcome gap <= action gap | PASS expected |

## Pre-registered rules
- If H1 passes and H2 fails: the ruler works; the flat harmed-control is outcome dominance.
- If H1 fails too: the model does not separate actions even without an outcome; no
  action-sensitivity claim is possible, and the earlier "instrument invalid" verdict stands.
- Examples, not a rate. One model, 5 trials, 6 cells.
