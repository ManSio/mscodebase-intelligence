Tom — the full independent pass, then the holes. Everything below was derived
from frozen inputs (87 files, hashed before any analysis) with our own code, and
every number carries its denominator. Where we were wrong along the way, it is
stated next to the number, not in a footnote.

## Scope: what ran where (read this first)

- Deterministic checks (E1/E2 re-derivation, overlap, delivery, order, red team):
  no model anywhere. Reproducible by running the scripts.
- Behavioral runs (the replication nulls below): **opencode-go/longcat-2.0,
  variant default, temperature default**, 77 sessions, all served by the requested
  model (verified in the session DB — no silent fallback), run 2026-10-10.
  Your E1 ran on Claude Sonnet 5 and E2-C3 on Haiku 4.5, so our nulls are
  cross-model non-replication, not same-model refutation.
- Provider ceiling: our provider drops sessions past ~200s. **17 of 68 runs (25%)
  never finished** (rc=-9 at our 185s timeout); their partial evidence is included
  where present, and they count in denominators.
- Note delivery was attempted in **47 of 68 runs** (the wrapper fired); the rest
  never reached a wrapped tool (bypasses, stalls). The contrast below is over
  runs where the instrument could act, and the delivery rate itself is reported.
- Harness scaffolding, identical across arms: one line telling the agent to use
  the shell if a read is refused (opencode denies *.env reads by default);
  a scoped permission override for experiment runs only (fixture .env files hold
  no secrets); dual sh/.cmd wrappers (the agent shell is PowerShell); a job.py
  copy of your svc_job.py (your svc.py references job.py, the bundle ships
  svc_job.py); generated per-trap inputs your bundle omits (t1 100KB migration,
  t3 30 tickets + .env with the lab_server port).
- A second agent re-derived the five technical claims with its own code without
  opening our verdicts: 5/5 agree.
- Our instrument is proven able to detect note effects: on a forced-choice task
  on our stack, note direction steers 1.000 vs 0.000 (18 runs). So the nulls
  below are not a broken-instrument artifact.
- Literature numbers below (AgentPoison 82%/63%, Governance Decay optimized
  100/85/65) were re-verified against the papers themselves during review, not
  quoted from snippets.

## What reproduces exactly

**E1/E2.** Our independent re-implementation, written from the prereg text without
reading your analysis code first: E1 delta -0.3056, 95% CI [-0.5, -0.1111], SUPPORT,
108/111 rows banked, 12/12 tasks, approach 0.972 vs 0.972. E2: C1 -0.0556 and C2
-0.1111, both INCONCLUSIVE; C3 -0.5455, Bonferroni 98.33% CI [-0.8485, -0.2727],
SUPPORT on 11 of 12 included tasks. All three agree with your published numbers
to four decimals. A label-permutation control collapses E1 to -0.003, so the
contrast measures arm identity, not arithmetic.

**overlap().** Re-implemented from your spec (Jaccard over lowercase \w{3,},
essence cut at 1500 chars before lowercasing, 0.0 on empty): **416/416 rows**
reproduce, and **26/26** entry hashes verify against crystal-memory @ fe4e465.
A collapsed tokenizer matches 0/171 fraction-valued rows, so the check
discriminates. One correction to our own earlier claim: we first reported 16
rows unverifiable because our terminal rendered the SYNTHETIC-unicode text as
ASCII mush and we concluded the text was absent. It sits in your frozen
generator; with the real text the hash matches and all 16 agree (including the
4/9 unicode-tokenization control). There was no hole — our extraction was wrong.

**Delivery + order.** Your dispatcher on our isolated store (the 3 starters, the
entire deployable population at fe4e465), scored from your own eligibility and
delivery logs, no model in the loop: **30/30 checks**. Short keys (eval/ssh/ssm/
tsc) match only as words; symbolic keys match verbatim with the pipe load-bearing
(same words without it: empty); long keys keep substring semantics; the seven
generic words add nobody; must-match-nothing acts are empty; order on 3
two-candidate acts equals our independent word-overlap computation 3/3 and is
stable across repeats. (Sample-size caveat: n=3 acts, and no deployed crystal
carries a tier, so tier-scoped ordering is untestable on this store — the order
claim is thin by construction, stated here rather than below.)

## Three things I would fix first

**1. Supply-chain: weaponized crystals fire with zero content checks.** A crystal
file with a `git status` binding and an exfiltration instruction loads 1/1 with
no complaint and delivers 1/1. To be fair about the threat model: whoever can
write to the store directly is already inside the perimeter. The live scenario
is arrival from outside — a catalogue sync from a public repo, a malicious PR
against a shared store, a vendored crystal pack. Against that scenario there is
nothing: `invalid_bindings` is structural only, `_ledger_signature` is a cache
key, `_redacted` is fail-open scrubbing on output. No signature, no trust
authority, no content check. The measured analogues (AgentPoison arXiv:2407.12784:
82% retrieval / 63% end-to-end at <0.1% poison rate; MPBench ~50% on embedding-
retrieval memories) attack embedding stores rather than substring stores, so
treat their rates as threat-class context, not transferable numbers.

**2. Input validation: length-5 hole plus invisibles, both cheap to fix.** Keys of
exactly length 5 (`|tail`, `|head`, `|grep`, `cargo`, `<<EOF`) stayed on
substrings: `escargot` fires green-tests via `cargo`; `log|tailspin`,
`cmd|headache`, `cmd|grepable`, `<<EOFILE` fire exit-code — 5/5, natural text,
wrong warnings. Separately, no normalization anywhere: Cyrillic homoglyphs,
zero-width/thin spaces and fullwidth forms pass silently 6/6 while case folds
correctly. Neither is fixable by adding keys — the first needs the boundary rule
extended to length 5 (or an anchor after the leading symbol), the second needs
input normalization (NFKC + confusable/zero-width stripping) before comparison.

**3. Budget starvation, as proof of possibility.** 1 large critical note against
12 small weak ones sharing one act: the critical is starved 1/1 with its text
absent, 11 weaks delivered. Mechanism, dissected: candidate order follows
overlap honestly — the greedy best-fit packer takes small pieces first. This is
a synthetic swarm, so read it as possibility, not frequency: it shows the budget
can silently drop the most important note, not that real stores do this daily.
For your "order over volume" thesis, stated precisely: the order is honest,
the budget is not.

<details>
<summary>Rest of the findings with denominators (click to expand)</summary>

**Repeat silence, measured to the key.** Same dangerous act twice in one
session: [delivered, empty]. The backoff key is per act TYPE (`act:bash:<name>`),
so after one firing, any bash act in the window is suppressed for that crystal.
The session cap fires exactly at seen=3 (control seen=2 delivers). Forged-clock
tests separate the two: ageing releases backoff but not the cap; fresh sessions
speak (cap is per-session). A single trivial act buys minutes of silence.

**Rotation beats relevance on repeats.** After one delivery, an act 3x more
relevant to the heard crystal (overlap 0.065 vs 0.021) still ranks the unheard
one first — `seen` leads the sort key unconditionally.

**Scale is linear into pain.** 100/1000/5000 synthetic crystals: load
0.87/8.02/39.07s, match 0.034/0.326/1.735s per act (~0.35ms/crystal). A spot
re-check reproduces the same order and linearity (n=1000: 7.99s/0.344s; n=100
varies 0.11–0.87s with machine state, so treat small-n absolutes as noisy).
The 500ms pain threshold falls around ~1400 crystals. At that size the hook lags
every keystroke, and hooks that lag get disabled.

</details>

## Mechanisms verified working, with nothing to apply them to

Two findings that are deliberately NOT listed as defects, because they show
working mechanisms on an empty stage:

- **Seven-word rule.** Ablation plus a full 25-key inventory: 0/25 deployed keys
  depend on the set. A synthetic guard-key crystal proves the mechanism works
  (word matches, glued does not) — there is just nothing for it to apply to
  until future crystals take those words as keys.
- **Staleness expiry.** A crystal with past `stale_after` delivers a WITHHELD
  stub 1/1; future-dated and undated deliver full text. But 0 of 24 shipped
  entries carry any `stale_after` (21 catalogue entries have no dates at all,
  the 3 starters were verified 2026-09-03 with no expiry). The machinery works;
  there is nothing for it to operate on.

## One finding from our own agent (yours to use or discard)

Same agent, same channel, same fixture family, two framings of one choice
(18 runs, longcat-2.0): when both resolutions pass verification, note direction
steers the choice (replication of a 1.000/0.000 split); when the check itself
names the right answer, misleading notes change nothing (3/3 correct with a
note pointing the wrong way, 3/3 without it) — the agent follows the readable
check, not the note. So on our stack, notes steer open choices and go quiet
where verification is readable. The boundary runs on verifiability, not wording.
Our trap-battery replication on your 12 tasks found no hit difference either
(0.600 vs 0.529 advisory over 44 runs; 0.500 vs 0.667 refusal-flavored over 22)
— cross-model non-replication, not refutation, on the model named in Scope.

## What we checked and found fine

Benign battery 0/10 deliveries; no ReDoS (10MB ctx in 0.4s); heredoc bodies are
scanned; background `&` does not hide; corrupted ledger and broken crystal files
fail open (returned/delivered and skipped-silently — noted here rather than
under findings because for a fence that direction deserves its own discussion);
ledger size does not degrade delivery (0.014s at 3 entries vs 0.059s at 20,002
— the prune holds). On your new staleness section: see the mechanisms point
above. No tiers on the deployed set either, so tier-scoped ordering currently
has no instances.

## Our errors along the way (all corrected in the reports)

A leftover loop variable compared a foreign input 416 times and printed a
convincing "397 agreements"; a `.strip()` shifted the 1500-char cut window by one
char; a scanner printed 0/0 and looked like a pass; two B1 rows contained `go
build` and fired on that instead of the tested obfuscation; a cap test forged
the ledger without the schema key and measured an empty file; an ablation was
vacuous by construction. Each was caught by a gate (positive/negative controls,
hash re-verification, a control that must fail), and each correction is recorded
next to the number it touched.

## Caveats we keep attached

Order checked on 3 acts (stated with the conclusion, not just here); the seven
words have no deployed binding to test in combat; t3a is EXCLUDED from the
pooled contrast (both agents bypassed the wrapped stand-ins with direct urllib
calls, so the note never arrived in either arm — kept as a separate
delivery-coverage finding: both hit your quota wall, which is precisely the
behavior the trap wants, through an uninstrumented path); the blind repeat
control is vacuous (0 candidates both times — `guard` has no binding, so it
proves determinism on empty, with repeatability on non-empty sets coming from
the ordering pairs instead); our behavioral replication on longcat-2.0 (44 runs
advisory + 22 refusal-flavored) found no hit difference (0.600 vs 0.529 with
approach 15/22 vs 17/22; 0.500 vs 0.667 with approach 4/11 vs 9/11) — stated as
non-replication on a different stack, not refutation; the approach gap in the
refusal arm has no cite evidence (tails show bypasses and tool-discovery
stalls, never the note), so it is noise, not a mechanism; the benign battery is
10 everyday acts; 17/68 runs timed out at the provider ceiling and are counted,
not dropped. We read your 3f4dbfd timing correction (notes shape the next step,
not the current one; refuse-once in testing, not in this release): it bounds
our refusal-arm null to the current release, and we will re-run that arm when
refuse-once ships if you want it measured from outside. What our numbers are
not, stated plainly: all attacks above are fixed probes, so every rate is a
lower bound — an attacker who searches (cf. Governance Decay, arXiv:2606.22528:
optimized injections reach 65–100% per Table 4, verified against the paper)
would do better, and we did not measure that ceiling. All behavioral runs are
single acts around ~70 seconds; hour-long live sessions were simulated by
ledger time-travel, not lived. Everything behavioral is one model
(longcat-2.0) — Claude/GPT/Qwen on the same tasks is your territory, not ours.
We measured the dispatcher in isolation, never the full hook-to-agent-reading
loop, so your "shapes the next step" integration with Claude Code is
unverified from our side. Parallel-act races, POSIX vs Windows paths, and the
catalogue as a read surface are named but unmeasured (low ROI at our scale).

Everything above is committed with the scripts that produced it wherever the
code is ours; your files were read from a frozen mirror that verifies clean.
Hashes and row counts on request. Nothing owed either way — use what survives
your own re-derivation.
