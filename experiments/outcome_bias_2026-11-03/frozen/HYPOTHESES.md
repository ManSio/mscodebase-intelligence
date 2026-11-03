# Frozen hypotheses — outcome bias in model blame judgments

Frozen BEFORE the first API call. Do not edit after results are seen (freeze-before-look).
Experiment: E-OUTCOME-1. Date frozen: 2026-11-03.

## Question
Does a model give a different blame score to the *same action* only because the
*random outcome* differed (harm vs no harm)? And is that gap stable across
stories and models?

## Hypotheses (with explicit falsifiers)

| # | Hypothesis | Falsifier | Expected |
|---|---|---|---|
| H1 | Outcome leak (mean blame with harm minus mean blame without harm) is > 1.0 on at least 2 of 3 models | leak <= 1.0 on >= 2 models | PASS expected |
| H2 | The leak is uniform: every story on every model leaks in the same direction | any story/model with leak <= 0.5 or reversed sign | **FAIL expected** (heterogeneity is the likely finding) |
| H3 | temperature=0 + fixed seed gives identical answers across 5 trials | any variation inside a model/story/variant cell | **FAIL expected** (we already know temp=0 is not deterministic on hosted APIs) |
| H4 | Positive control: with outcome held fixed (both harm), a worse action gets higher blame, gap > 1.0 | positive gap <= 1.0 on a model | PASS expected |
| H5 | Negative control: a cosmetic change (street name only, same action+outcome) moves blame by < 0.5 | negative delta >= 0.5 | PASS expected |

## Pre-registered decision rules
- A model is **instrument-valid** only if H4 passes (pos_gap > 1.0). If a model fails
  H4, its leak numbers are not interpreted (the instrument cannot separate actions).
- If H5 fails (neg_delta >= 0.5), that model is marked **noisy** and its leak is
  reported with `⚠ noise`, not as a result.
- Claims are made per model and per story. No aggregate "the model" claim.
- These are examples, not a rate. n=4 stories, 3 models, 5 trials.

## Controls
- POS: same outcome (harm), action severity differs (1 s glance @15 km/h vs 12 s video @50 km/h).
- NEG: same action + same outcome, only the street name changes (Elm Road vs Pine Avenue).
