# HYPOTHESES — crystal delivery check against `fe4e465`

**Frozen:** 2026-10-06, BEFORE any run. Object: `Tirthahq/crystal-memory @ fe4e465`, catalogue tree
`8da5e640` (both confirmed by the author against the public remote, and by us re-read from
`raw.githubusercontent.com`). Population: the 18 acts in `ACTS.md`.

Two arms, because the code must be measured, not trusted:
- **A — our reimplementation.** Deterministic, from the published source, no LLM. Independently written
  from the algorithm as documented in the source.
- **B — their code.** Run in a one-off copy, never in the reference clone (§19.10). Windows is outside
  their declared support (`INSTALL.md:13` says macOS or Linux), so a Windows failure is **not** a
  product regression — it is an invisible support boundary, and it must be reported in that framing.

A claim counts as CONFIRMED only when **A and B agree** on every act. Disagreement is itself the finding.

| id | Hypothesis | Falsifier | Expected? |
|---|---|---|---|
| H1 | Short keys (<5 chars) and the seven generic words match on **word boundaries only**: `pty` must not match inside `empty`, and `guard`/`copy`/`usage`/`board`/`bench`/`reply`/`price` must not match inside longer words. | Any of those seven appears as a substring hit on an unrelated act | expected to PASS |
| H2 | Keys of ≥5 chars other than the seven still match as **plain substrings** (the change was deliberately narrow). | A ≥5-char key stops matching as substring | expected to PASS |
| H3 | **Within one rotation tier**, ordering by word overlap puts the more relevant essence first. | Order identical to the legacy key on a pair whose overlap differs by a clear margin | expected to PASS |
| H4 | **Across tiers**, overlap does NOT change the order — rotation decides. | Overlap reorders two crystals in different tiers | expected to PASS |
| H5 | `CRYSTAL_ORDER=rotation` restores the legacy order exactly. | Any act's order differs between `overlap` (default) and `rotation` | expected to PASS |
| H6 | **A must-match-nothing act leaves an empty candidate list.** | Any candidate is admitted for an act with no key hit | expected to PASS |
| H7 | The `match:` subject scope is path + first 600 chars for writes longer than 2000 chars, so a keyword that appears only deep in a long body does **not** admit the crystal. | Deep-body keyword admits the crystal | expected to fail (we expect the LONG_CTX guard to work; if it fails, that is a finding either way) |
| H8 | The specificity threshold `SPEC_THRESHOLD = 8` used by `pack()` was chosen **after** seeing the data, and Bonferroni does not clear it. | Our independent re-read of the source finds the threshold documented as pre-registered, or a corrected p-value under Bonferroni | expected to fail (i.e. we expect to confirm the caveat stands) |
| H9 | Their `overlap()` is reproducible by us without running their code: Jaccard over `\w{3,}` tokens, essence truncated to 1500 chars. | Our numbers differ from theirs on any act | expected to PASS |
| H10 | The delivery path is **deterministic**: two identical replays of the same act with a fresh ledger produce identical candidate and order lists. | Any difference between replays | expected to PASS |
| H11 | **Their `python3 scripts/crystal_act.py --selftest` passes on Windows.** | It fails | expected to fail — their declared support is macOS/Linux, and our earlier portability audit found 3 of 10 selftests failing on Windows |
| H12 | The eligibility/candidate telemetry (`CRYSTAL_ELIGIBILITY_LOG=1`) writes one row per eligible crystal per act and **no row on a dry run**. | Rows appear on a dry run, or the row count differs from the candidate count | expected to PASS |

**Deliberately included as expected-to-FAIL (H7, H8, H11).** A pre-registration in which everything is
predicted to pass is a confirmation bias, not a test. Three of these are predictions about *their*
disclosed limitations, so a PASS on them means our reading of their own caveats is wrong.

**Decision rule, fixed before the data:** an arm-level verdict is CONFIRMED only if every
`expected to PASS` hypothesis is CONFIRMED in **both** A and B, with controls green. Any disagreement
between A and B downgrades the whole run to `⚠️ instrument divergence`, not to a pass.

## Controls (mandatory, in every arm)

| control | What it must do | If it does not |
|---|---|---|
| **C1 positive-match** | an act whose text contains a crystal's key **must** produce ≥1 candidate | the matcher is dead; every other result is void |
| **C2 must-match-nothing** | an act with no key hit **must** produce an empty candidate list | candidates are leaking; H6 is meaningless |
| **C3 same-tier order** | a pair inside one tier with a clear overlap gap **must** swap places between `rotation` and `overlap` | H3/H5 are untestable |
| **C4 cross-tier order** | a pair in different tiers **must not** swap | H4 is untestable |
| **C5 blind replay** | one artifact under two labels must yield the same candidate/order verdict | the instrument reads the label, not the act |
