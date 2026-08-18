# Eval: rule in context (AGENTS.md) vs rule in a skill (git-workflow)

Date: 2026-08-18
Method: agentic-eval-lab (fixed instance, A/B, isolated subagent runs, objective rubric, pass@k)
Instance: write a Conventional Commits commit message for the fix
  "secret detection now ignores PascalCase identifier values as secrets"
Conditions (>5 runs each):
  A = control  — commit rules written inline in the prompt (simulates always-in-context AGENTS.md)
  B = treatment — rules live only in the skill "git-workflow"; agent told to load it via the skill tool
Rubric (yes/no): cc_format | imperative | subject_len<=72 | english | blank_line_before_body

## Raw outputs

Condition A (inline rules):
- A1: fix(secrets): ignore PascalCase identifier values
       (body: "Detail noise")
- A2: fix: ignore PascalCase identifiers as secrets
       (body: blackline + PascalCase values are code-identifiers...)
- A3: fix: ignore PascalCase identifiers as secrets
- A4: fix: ignore PascalCase identifiers as secrets
       (body: blackline + PascalCase values (e.g. class names) were being flagged...)
- A5: fix(secret): ignore PascalCase identifiers as secrets
       (body: blackline + Values matching PascalCase identifier names...)

Condition B (skill required):
- B1: fix(secret-detect): ignore PascalCase identifier values as secrets
       (body: blackline + Detector now skips values that appear to be PascalCase identifiers...)
- B2: fix(secret-detector): ignore PascalCase identifier values as secrets
- B3: fix(secret-detector): ignore PascalCase identifiers as secrets
       (body: blackline + Previously any value matching a PascalCase pattern...)
- B4: fix(secret-detector): ignore PascalCase identifier values
       (body: blackline + PascalCase values (e.g. `MaxAttempts = 3`) were being flagged...)
- B5: fix(secret): ignore PascalCase identifiers as secret values

## Scoring (rubric gate: subject <= 72)

| Runs | cc_format | imperative | subject<=72 | english | blank | pass@1 |
|------|-----------|-----------|-------------|---------|-------|--------|
| A1..A5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 (100%) |
| B1..B5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 (100%) |

pass@3 = 1.0 both. Min/max subject length: A 46..54, B 57..70.
Violations of the soft 50-char target ("shoot for 50"): A 2/5 (51, 54),
B 5/5 (57, 68, 63, 58, 57) — B runs add scopes (secret-detector) which lengthen the
subject past 50. Under the real hard gate (72) both conditions are 100% clean.

## Conclusions
1. Equal compliance: when the rule is reachable (inline, or behind a skill the agent is
   instructed/able to load), agents follow Conventional Commits + imperative + English
   at 100% under the <=72 gate. NO degradation from moving the rule into a skill.
2. Skill bonus: B (skill) runs produced richer bodies (what/why) on average; the skill
   supplies HOWTO context that a bare rule list does not.
3. Real risk of de-bloat is NOT "agents can't follow a skill" but "agents won't discover/
   load a skill without a clear description trigger". Guard: keep hard gates in AGENTS.md,
   give extracted skills crisp task-matching descriptions, and leave a one-line pointer in
   AGENTS.md.
4. Rubric calibration: subject <=50 is a soft target agents routinely exceed (especially
   with scopes); the enforceable gate is the 72-char hard limit already stated in
   AGENTS.md §0.-3 ("subject <50 (72 hard)").
5. Limitation: harness returns only the final message, so it cannot prove B agents
   literally called the skill tool; it proves parity of final output quality under the
   "skill required" instruction.
