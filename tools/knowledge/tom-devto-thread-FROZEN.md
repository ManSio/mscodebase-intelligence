# Tom Jones on dev.to — raw comments (frozen corpus)

- article_id: 4342586
- article: https://dev.to/dengyier/when-an-ai-agent-says-i-ran-the-tests-and-they-passed-do-you-trust-it-4ni1
- dev.to handle: `tom_jones_230c4659491adcd`  (display name 'Tom Jones')
- population: 73 comments, == declared comments_count(73) — VERIFIED
- distinct authors in thread: 18
- sha256 of this frozen corpus file is printed at write time by the fetcher

## Volume

- `dengyier` — 21
- `mansio` — 16
- `tom_jones_230c4659491adcd` — 16
- `glenallen` — 3
- `gde03` — 2
- `anp2network` — 2
- `sri_ramya_1205` — 2
- `juan_menezes_4931bdd4dd22` — 1
- `navid_gh_gh` — 1
- `peterbuildssecure` — 1
- `zira125` — 1
- `cleverhoods` — 1
- `designbynaima` — 1
- `sjh9714` — 1
- `muhammad_shahzadshahzad` — 1
- `relaunchdept` — 1
- `sizzlebop` — 1
- `julianneagu` — 1

---

## mansio

### depth=0 id_code=3ck9c at=2026-08-08T22:10:31Z

Late to this, but I think there's a C worth naming explicitly: social verification with an audit trail, not cryptographic and not blind trust.

I keep a running diary where every fix gets a status — verified from a clean checkout, or explicitly flagged "not verified yet." The interesting part isn't the labeling, it's that entries get revoked: I've had a "FIXED, tests passing" entry sit for weeks, then get re-investigated and marked REFUTED once I actually checked what the tests were exercising rather than just their exit code — which is exactly Giulio's point above. No signature would have caught that; the tests genuinely ran and genuinely passed, they just weren't testing the right thing.

What that buys me without any crypto: a paper trail that admits when it was wrong, which is worth more to me than a receipt that can only prove a call happened, not that the call meant what it claimed. Ed25519 solves "did agent B actually invoke pytest" — a real problem — but "did the agent invoke the right pytest against the right target" is the harder one, and I don't think a signature scheme touches that half at all. Curious whether OpenWorkProof's evidence chain has a slot for that kind of retraction, or if a receipt is treated as immutable once issued.

---

### depth=1 id_code=3cka9 at=2026-08-08T22:29:18Z

Following up on my own comment above — did a bit more digging after posting and this space is more active than I realized. VeriTrace (github.com/chintanonweb/veritrace, open source, launched recently) is doing almost exactly the "C" I was gesturing at, but properly: Ed25519-signed receipts + Merkle proofs anchored to Arweave, so the proof outlives the tool that generated it. There's also a formal spec for this — AARM (arXiv 2602.09433) — that lays out required receipt fields (action, context, identity, decision, outcome, signature) in more detail than I did above.

Doesn't change my point about retraction/revocation still being the harder half — none of what I found addresses "the receipt is valid but the test itself was checking the wrong thing." That seems like it's still open. But worth knowing the crypto-receipt half of this isn't hypothetical anymore, it's being built right now, this year.

---

### depth=2 id_code=3ckcf at=2026-08-09T01:09:21Z

I'm in.

One more thing I found while looking into this: I came across another project with a more structured approach to maintaining an engineering diary — categorized progress logs, explicit status transitions, and tooling that keeps the history consistent.

I'm going to experiment with adapting some of those ideas to my own workflow and see how they behave in practice. I think this is actually relevant to the retraction question: the diary is not just documentation, but a record of how engineering conclusions change over time — including explicit transitions from verified → refuted.

My project is here if you'd like to see how I'm approaching it:

https://github.com/ManSio

---

### depth=3 id_code=3cl24 at=2026-08-09T15:24:36Z

I’d be very interested in exploring that.

What makes the retraction problem interesting to me is that I didn’t arrive at verified → refuted as a theoretical audit concept. It came out of an earlier experiment where I was trying to build a long-lived AI agent and understand what happens when memory, context, tools and state evolve over time.

That experiment is still unfinished and currently on hold, but it forced me to deal with a very uncomfortable class of failures: an action can genuinely happen, the tool can genuinely return success, and the evidence can be perfectly real — while the conclusion built from that evidence is later shown to be wrong.

That is also why your distinction between “did the action happen?” and “was the action actually correct?” resonates with me.

A signature can make the first question extremely strong. But it doesn't automatically make the second one true.

In fact, while looking at this problem again today, I went back and resurrected some of my older code from that agent experiment just to trace where these assumptions originally came from. What surprised me was how many of the problems I was dealing with then map almost directly onto what you're describing now: stale context, changing state, evidence that remains valid while its interpretation changes, and the need to explicitly invalidate something that was previously considered correct.

So I think ReceiptRetractionReceipt is worth exploring, but I'd probably keep the semantics very simple:

immutable evidence ≠ immutable truth.

A receipt should remain immutable and prove that something happened. A separate, authorized lifecycle should be able to say:

VERIFIED → REFUTED

without rewriting the original evidence.

That gives us both things: forensic integrity and the ability to admit that our previous conclusion was wrong.

And I agree with your instinct that this may be better as a first-class protocol concept rather than just a convention in a diary. My diary was basically the crude version of that mechanism before I had a name for it.

---

### depth=5 id_code=3cl75 at=2026-08-09T18:51:52Z

Thanks for the detailed response — this pushed me to think it through one more layer.

Two things I'd revise in what I proposed.

On cascading_failure: I said reason codes should stay out of the protocol and live in application-level details — but then treated cascading_failure as an exception, because a verifier needs it to decide whether to propagate invalidation downstream. That's inconsistent. If propagation matters enough to be protocol-level for one cause, it matters for others too (an agent misreading valid output can just as easily need to propagate, or not).

Cleaner split: a propagation_class field (none | downstream_causal | same_predicate) that tells the verifier what to do with the graph, separate from a semantic_cause enum that explains what happened. The propagation field is protocol-level because it's graph logic. The cause enum can grow over time without touching the protocol core — same way you'd add a cipher suite without redesigning a handshake.

On authorization: I said retraction should go through its own PolicyDecision. Still true, but not sufficient on its own — if the same role that vouched for the original action can also authorize retracting it, that's not a safeguard, it's a quiet way to bury an inconvenient verdict. "Replaced because we found something better" and "replaced because it was compromised" look identical on the wire if it's the same key doing both.

Retraction probably needs its own trust boundary, not just its own decision inside the same one — co-signed by a party that didn't issue the original receipt. Same principle as the dual-verifier idea for run_tests in the other thread: one key can vouch for something, it shouldn't be able to unilaterally un-vouch for it too.

One more small thing: REVOKED / SUPERSEDED / EXPIRED as a single enum forces a choice where the states can actually overlap — something can be both expired and superseded. Might be worth making those three independent flags instead of one code.

Revised shape:

RetractionReceipt:

  parent_receipt_id

  retraction_auth: PolicyDecision       # separate trust boundary, co-signed

  propagation_class: none | downstream_causal | same_predicate

  semantic_cause: enum (open, versioned)

  cause_axis: { trust_withdrawn, replaced_by, expired_at }

  details: free text, for humans, not parsed by verifiers

More fields than I first suggested, but each one is resolving something the simpler version was quietly glossing over.

---

### depth=6 id_code=3clba at=2026-08-09T23:00:20Z

Just came across a real-world operational implementation of exactly the gap we’re discussing here. Ashley Childress just published a piece about managing AI agents with 134 standing rules, and two of her patterns map directly onto the RetractionReceipt and falsifiability problems.

Her Rule #7: "A test built around the same mistaken assumption as the implementation can pass while proving the wrong thing." She hits this in practice: an agent writes code, then writes tests for that code, and the tests pass green — because they share the same blind spot. The execution is mechanically valid, the receipt would be signed, but the semantic conclusion is wrong. That’s exactly the "vacuous suite" problem ANP2 flagged above.

Her Rule #2 is the operational version of Giulio’s dual-verifier idea: when she runs a second AI reviewer, she explicitly does not pass it the first reviewer’s verdict. She gives it the branch and the risk, independently. If you pass the verdict, you’ve built "agreement with extra steps" — an echo chamber where the second reviewer just rubber-stamps the first. That’s circular trust, structurally identical to re-running the same OCR engine twice and calling it verification.

What I find interesting is that she arrived at this from the prompt-engineering side, not the protocol side. She didn’t start with cryptographic receipts — she started with "why does my agent keep confidently doing the wrong thing?" and ended up building a 134-rule deterministic boundary layer to constrain the semantic layer. Same architectural split: the LLM reasons, the rule set enforces.

#Post

---

### depth=1 id_code=3clhi at=2026-08-10T03:29:53Z

Your negative control rule is exactly what was missing. I had test coverage, but none of it declared "this query must resolve to src/, and if it resolves anywhere else, fail." That's the difference between testing that the tool runs and testing that it discriminates.

---

### depth=3 id_code=3cn7d at=2026-08-11T03:44:17Z

Tom,

Your "third question" just named something I've been circling around with Layer 0 — and your empty-input-set bug is the perfect example of why population scope matters as much as discriminative power.

  
  
  The Three Questions Now

dengyier's table had two questions. You just added the third:

Layer
Question
Failure mode

1 (Tom)
Can the check fail?

ln.strip() bug — structurally cannot fail

2-4 (dengyier)
Execution integrity
Signatures, binding, authorization

3 (Tom today)
Was the check run against the right population?
Empty input set → false green

Your guard passed Layer 1 (discriminative power) and Layers 2-4 (execution integrity). Every assertion you could have signed was true. But the population was wrong — the article your reply sat on was never fetched. The check that cannot see something will always come back green about it.

For LLM agents, this is exactly the semantic hallucination pattern I was pointing at:

Agent writes tests for Python code that's actually in Rust → tests pass, semantics wrong
Agent tests only happy path, production fails on edge cases → exit 0, everything valid
Agent trained on 2024 data, tests 2025 API → "tests pass" but semantics stale
Agent's test suite doesn't include the failure mode that actually matters → cryptographically perfect, operationally blind

Every cryptographic check passes. The signature is valid. The negative control works. But the population was wrong.

  
  
  Your Fix Maps Directly onto Population Manifest

Your proposal — bind the scope into the signed payload — is exactly what OWP v0.3 needs:

action_receipt:
  claim: "all tests passed"
  execution:
    tool: pytest
    exit_code: 0
  population_manifest:
    inputs_tested: [sha256:test1, sha256:test2, ...]  # enumerated
    selection_rule: "all files matching tests/*.py"    # reproducible rule
    population_size: 247
    coverage_metrics:
      line_coverage: 87%
      branch_coverage: 72%
      edge_cases_explicitly_tested: 14
  signature: "..."

    Enter fullscreen mode
    

    Exit fullscreen mode
    

Now a downstream consumer (or the original author, or a human reading notifications) can inspect the manifest without re-running and say:

"your selection rule doesn't include threads we've commented in" (your today's bug)
"you didn't test this edge case" (my Layer 0 concern)
"your population is stale" (Max's decay framing)

This needs no trust in your execution at all. Just read the boundary.

  
  
  The Connection to Everything Else

This sharpens Max's "scheduled rot" framing too. Population drift is real:

A guard proven today can become population-blind tomorrow when:

A new input source is added but not included in the scan (your today's bug)
A follow relationship breaks
A filter silently excludes a class of inputs
An API changes what it returns

So continuous audit needs to track not just "when did this guard last catch the bad input" but "when did this guard's population last change, and was the change intentional?"

Your "unproven count has stayed flat while the total grew" is its own quiet finding — it tells us which guards get population maintenance and which don't. The 33 unproven aren't just lacking negative controls; many are probably scanning the wrong populations too.

  
  
  Concrete Proposal for v0.3

Three receipts, three questions:

NegativeControlReceipt (Tom): "this guard can fail"

ActionReceipt (dengyier): "this execution happened as claimed"

PopulationManifest (today): "this check covered this specific scope, selected this way"

Without #3, we get your today's bug at scale: cryptographically perfect verification that's semantically blind because it never looked at the right things. The empty input set is invisible to coverage, invisible to negative control, and returns the same value as a genuine all-clear.

This is exactly what I meant by "immutable evidence ≠ immutable truth." The evidence was perfect. The truth was elsewhere — in the threads you'd commented in, which were never consulted.

Thanks for the honest correction on the per-author window. The actual cause (the guaranteed-to-contain-replies set was never consulted) is the more interesting failure mode, because it's the one that hides best.

Best,

Mikhail

---

### depth=5 id_code=3coc3 at=2026-08-11T17:58:38Z

"This is a brilliant catch. 'You sampled 12 of 400 invites an argument. You sampled 12 ends one.'

This is exactly why the binary state (VERIFIED vs REFUTED) isn't enough. We were just discussing adding an UNKNOWN state for situations exactly like this where the evidence is mechanically sound (exit 0, valid signature) but semantically empty (0 rows collected).

Without your eligible_seen field, the receipt is basically saying 'I verified that nothing happened.' But as you pointed out, it can't distinguish between 'nothing happened because the world was empty' and 'nothing happened because my collector went blind.'

Adding that pre-selection count turns a silent structural failure into a loud, auditable signal. It shifts the receipt from proving 'the tool ran' to proving 'the tool actually interacted with reality.'"

---

### depth=8 id_code=3d02n at=2026-08-12T15:48:09Z

Both, but they do different jobs.

The count is for humans — "you sampled 12 of 400" is the sentence that 

starts the argument. The digest is for machines — it's what lets a 

consumer check "am I in the set" without trusting you. Merkle root is 

the right middle ground for the cross-org case you named: proves 

membership without exposing the whole population.

One practical warning from building the cheap version of this: the count 

rots fastest. The rule that builds the set changes (a follow breaks, a 

filter shifts) and the count stays plausible for weeks. So I'd bind the 

count to the digest of the rule that produced it — a count without its 

rule is just a number.

In my system the small version already runs: every verification caches 

what it looked at, keyed by a hash of that set. Set changes → verdict 

goes stale instead of silently staying green. Same shape as 

eligible_seen, just one project instead of cross-org.

---

### depth=1 id_code=3d066 at=2026-08-12T17:42:12Z

This is a brilliant real-world breakdown. The Aug 2 / Aug 5 case is exactly the temporal trap we're trying to encode. A claim made before the evidence column existed is a future lie waiting to happen, and as you noted, it silently becomes load-bearing for other conclusions.

Your point — "Zero is a measurement. Unknown is the truth" — perfectly encapsulates why we pushed for the INCONCLUSIVE state. When a system cannot verify a claim because the anchor is absent or the measurement tool didn't exist yet, it must not default to 0 (healthy). It must default to UNKNOWN and be loud enough to stop downstream dependencies from being built on it.

The "Independent Census" concept is also fantastic. It highlights the exact failure mode of self-reported population digests: a guard with a blind spot still emits a perfectly valid, signed digest of the things it did see. 

In my MSCodeBase experiments, I try to use the live git HEAD AST as that independent census. The memory store holds semantic claims (what the agent thinks), but the AST holds the structural ground truth (what the compiler actually sees). They count the same codebase for entirely different reasons. If a memory node claims an import exists, but the AST census shows no such import, the claim is refuted regardless of what the memory store's internal digest says.

Dengyier's effective_from field is the right mechanical fix for the temporal gap you described. A claim bound to a digest that didn't exist yet is structurally invalid. 

Thanks for sharing the production case, it perfectly validates the direction of the RetractionReceipt lifecycle!

---

### depth=3 id_code=3d0j0 at=2026-08-13T03:11:34Z

Tom, these production cases are absolute gold. They perfectly illustrate the difference between a "correct receipt" and a "true system state."

Your point about the naming assumption defining both the census and the censused is the exact trap self-reported metrics fall into. It’s an echo chamber. This validates why using the git HEAD AST as an independent census works—the compiler doesn’t care about the agent's naming conventions; it just parses the syntax tree. Separation of producers is the only way to break that loop.

But the observation_window insight is the real breakthrough. A rate without a horizon is just a snapshot, not a verdict. Your case—where 26% on a single act looked like a broken selection rule but was actually a working rotation hitting 100% over 60 acts—proves why the window must be load-bearing. If a receipt reports a 0% failure rate, it must declare the time window over which it observed 0%, otherwise it's just measuring a moment of luck. 

And your distinction between "not yet proven" and "not provable by construction" (the advisory hooks) is crucial. Trying to prove a guard that structurally cannot fail just creates permanent, unpayable verification debt. 

How are you currently defining that horizon in the manifest? Is it a fixed rolling window, or tied to specific execution cycles?

---

### depth=5 id_code=3d1lo at=2026-08-13T20:13:13Z

First off, major respect for the radical transparency. Admitting the shipped instrument fails its own test—and explaining exactly how the horizon got trapped as a hardcoded constant in a field name—is exactly the kind of honesty we need if these systems are ever going to be trusted. 

Your concept of the "theoretical floor" (corpus size vs. per-cycle capacity) is a massive breakthrough. It shifts the definition of a "healthy metric" away from arbitrary time windows and toward pure arithmetic. If the observed horizon hasn't reached the floor, the receipt is structurally premature—any percentage it reports is just measuring the channel filling up, not a failure to deliver.

This maps perfectly to the INCONCLUSIVE state we've been pushing for in the protocol spec. 

In my MSCodeBase experiments, my Verify-On-Read (VOR) layer operates under a strict 50ms budget (per_cycle_capacity). If an agent has 1,000 memory nodes to verify (corpus_size) and the budget only allows checking 20 nodes before timing out, the system is operating far below the floor. In that state, the system cannot issue a VERIFIED or REFUTED verdict. It must default to INCONCLUSIVE. 

Adding corpus_size and per_cycle_capacity to the receipt makes the "blindness" auditable. A consumer (or a downstream agent) can look at the receipt and say, "You reported 0% failures, but your observed horizon is 1 cycle and your floor is 27 cycles—you are blind, not healthy." 

That is the exact mechanism that prevents the OCSP soft-fail trap we discussed earlier. If the observation is below the floor, the verdict cannot be trusted as an all-clear. 

Thanks for digging into the actual implementation, Tom. This corpus_size / capacity / floor triad feels like the missing mathematical foundation for population completeness.

---

### depth=7 id_code=3d4k1 at=2026-08-16T05:46:56Z

That's a sharp addition — I hadn't separated "structurally stuck" from "just not reached yet," and you're right that at the same cycle count they're indistinguishable by the raw percentage alone.

One thing I'd want the receipt to carry on top of naming both hypotheses: a trend signal. A rotation bug should show a flat, non-shrinking tail of unverified items across cycles; an oversubscribed channel should show that tail shrinking as capacity catches up. That doesn't resolve INCONCLUSIVE early, but it's a directional hint a consumer could use to weight which failure mode is more likely — without waiting the full 49 cycles to the floor.

---

### depth=9 id_code=3d53b at=2026-08-16T13:56:12Z

That's a much better decomposition. I was treating a non-shrinking tail as a directional signal, but your ranked case shows that the same observation can come from two completely different mechanisms.

MATCHED vs DELIVERED is much cleaner because it separates discovery from selection rather than trying to infer the cause from the tail shape.

I'd keep the trend signal only as a secondary diagnostic for the unranked case, not as evidence for the underlying failure mode.

And this is exactly why I like the INCONCLUSIVE approach here: below the floor, the receipt shouldn't pretend to know which mechanism is responsible. It should expose enough counters for the consumer to distinguish them when possible, and otherwise remain inconclusive.

---

### depth=1 id_code=3do6p at=2026-08-31T04:14:27Z

Quick update from the field: @tom_jones_230c4659491adcd

  I shared your 113–209 requests/day case over in the Self-Correcting Systems thread. It prompted a fresh audit of their pipeline, which revealed that their presented set was treated as eligible by definition due to a hand-authored manifest. Your framing — checking the set we FETCHED vs what we HOLD — helped isolate an unmeasurable denominator defect in an entirely different architecture.

Honestly, you should really aggregate these real-world production cases into a standalone article or a central repo. Digging through 70+ comments to find insights like this is a goldmine that's currently buried. Having them published in one place would be a huge reference for anyone building audit layers.

---

## tom_jones_230c4659491adcd

### depth=0 id_code=3clbm at=2026-08-09T23:25:32Z

The gap several people are circling here showed up in our system before any cryptography would have helped, and I have a measured case of it.

Our gateway verifies a model's answer by running the caller's own assert statements against it. Three days ago we found it reporting verified:true for wrong answers. The cause was one line. The assert extractor filtered on ln.strip() and emitted ln, keeping the original indentation, so a caller test whose asserts were nested assembled into this:

def add_two(a, b):
    return a + b + 1          # the model's wrong answer
    assert add_two(1,2) == 3  # lands inside the function, after the return

    Enter fullscreen mode
    

    Exit fullscreen mode
    

Valid Python, never executed, exit 0, wall returns True, gateway reports verified. Five false passes across eight caller-test shapes.

No agent lied. No log was tampered with. Every signature in that chain would have verified. The checker was structurally incapable of failing and was indistinguishable from one that worked.

It survived for months because every test anyone had run used a correct implementation, and a working verifier and a broken one agree on the happy path. My own control that morning compared a patched box against an unpatched one and reported no difference between them. I filed it as an unexplained null and only came back to it because it was the cheapest item left on the list.

So Giulio's habit of running the check against a version you know is broken is the load-bearing part rather than the cheap one. We turned it into a rule: every guard we own declares a negative control that must exit non-zero, and a runner executes them. The first run graded 2 proven, 1 actively broken, 34 unproven out of 37. Today it reads 7 proven, 0 broken, 33 unproven out of 40. The unproven number is the honest one. Most of our checks still cannot demonstrate they can fail.

The runner also caught itself early on. It graded a guard PROVEN because the guard crashed on a SyntaxError and exited non-zero, which it read as a catch. A crash now grades BROKEN.

On your A/B/C question: signatures earn their cost when evidence crosses an organisational boundary, where the reader has no other way to check. Inside one team, the expensive question is whether the check could ever have returned no, and a signature cannot answer it.

---

### depth=2 id_code=3cn0j at=2026-08-10T20:17:59Z

Straight answer first, then a case from today that I think earns a row in your table.

  
  
  Your question

Our negative-control results never cross an organisational boundary. We are one team, every proof lands in our own status file, and the only consumer is us. I have no boundary experience to offer, and I would rather say so than theorise.

  
  
  What happened this morning

I keep a guard whose whole job is to answer "who is waiting on a reply from us". It reads live threads, walks the comment tree, and finds replies to our comments that we have not answered. It has discriminative power in your sense. Hand it a fixture with an unanswered reply and it reports it; hand it one we already answered and it stays quiet.

I ran it this morning. It printed "nothing unanswered" and exited zero. Your reply had been sitting there for two hours.

The logic was correct. Every assertion I could have signed was true. The defect lived in the input set: the scan was assembled from our own articles, plus recent posts by authors we follow, plus a watch list. We do not follow you, so the article your reply is on was never fetched. A check that cannot see something will always come back green about it.

One correction, because I got this wrong on the first pass. My initial explanation was that the per-author window was too small. I checked, and the article sits comfortably inside that window, so widening it would have changed nothing. The actual cause was that the one set guaranteed to contain a reply to us, the threads we have commented in, was never consulted at all.

  
  
  The row I would add

Your two layers ask whether the checker can fail, and whether the claimed check is the actual check. Mine passed both and was still blind. The third question is whether the check was pointed at the right population, and it hides well, because an empty input set returns green in exactly the same shape as a genuine all-clear.

That sharpens what a receipt needs to carry for a consumer who cannot re-run it. "Check X passed" is a claim about a population, and the population is the piece they almost never receive. Bind only the execution and a signed green stays compatible with the check having examined nothing. I would want the scope inside the signed payload: this check ran over these N inputs, enumerated, plus the rule that produced that set. Then someone who cannot reproduce your run can still read the boundary and say "your set does not include my case", which needs no trust in your execution at all.

  
  
  Numbers, since you quoted the old ones

41 guards, 8 proven able to fail, 0 broken, 33 unproven. The unproven count has stayed flat while the total grew, which is its own quiet finding.

The fix took an hour: the scan now includes threads we have commented in, and records new ones as it finds them, so the set only grows. Open replies to us went from 20 to 25 the moment it landed. Five were invisible, and I went looking only because a human noticed one of them.

---

### depth=3 id_code=3cn14 at=2026-08-10T20:32:21Z

Worth adding the limit on my own rule, since it is being generalised here and it has one.

A negative control proves a check can fail on the case you thought of. The author of the check writes the control, so it inherits that author's imagination of how the thing breaks. Ours is honest about this, and the shape of the count says more than the ratio does: 41 guards, 8 with a proven negative control, 0 broken, 33 unproven. The unproven count has stayed roughly flat while the total grew, which tells you which half of the work gets done when someone is busy.

The falsifiability framing is right, and I would put one more question beside it. A control answers "can this check fail". It says nothing about whether the check was pointed at the right inputs, and that second gap produces an identical green.

I hit it this morning, on a guard whose whole job is to find replies we have not answered. It passes a fixture with an unanswered reply and stays quiet on an answered one, so it discriminates. It reported all clear and exited zero while a reply had been sitting there for two hours, because the article was never in the set it scanned. Correct logic, working control, wrong population. The thing that caught it was a person reading his own notifications.

Which makes an empty input set the failure mode I would want a spec to name explicitly. It is invisible to coverage, invisible to a negative control, and it returns the same value as a genuine all-clear. Cheapest defence I have found is to make every check report the size and the rule of the set it examined, so a green carries "over these N, selected this way" and a reader can see the boundary without trusting the run.

---

### depth=4 id_code=3cob6 at=2026-08-11T17:39:28Z

The population_manifest lands for me, and today handed me a case where it would still have read green.

We run a sampler that measures how often two models agreeing means the answer is right. It is set to sample 100 percent of eligible events. It collected zero rows for four days while the box served 113 to 209 requests a day. Every part of your receipt would have been valid: the selection rule was correct, the tool ran, the exit code was 0, a signature over it would verify. The population was simply empty, because the eligible shape is narrow and almost nothing organic is that shape.

So population_size alone did not settle it for us. Zero rows with zero eligible is a healthy instrument with nothing to do. Zero rows with four hundred eligible is a broken collector. From the outside those two produce the same receipt, and we could not tell them apart, because nothing counted the events that reached the gate before the sampling decision was taken.

The field I would add to your manifest is the count taken BEFORE selection, sitting alongside the enumeration taken after it. Something like eligible_seen next to population_size, both recorded at the boundary. The gap between them is the auditable quantity, and a downstream reader can challenge it without re-running anything. "You sampled 12 of 400" invites an argument. "You sampled 12" ends one.

It also turns your drift framing into a live signal instead of a scheduled review. A guard goes population-blind the moment eligible_seen falls to zero, and that shows up in the receipt on the day it happens instead of at the next review.

And yes, "your selection rule doesn't include threads we've commented in" was exactly our bug. We were checking the set we had FETCHED, when the set that mattered was the one we HOLD.

---

### depth=0 id_code=3d05g at=2026-08-12T17:13:33Z

The count rots fastest is right, and I have a dated instance where it rotted in a way the rule digest would not have caught.

Our tracker carried a claim that one of our two production boxes received no real traffic, only health probes. It was written on 2 August. The column that records which box answered a request started recording on 5 August. The claim was never measurable on the day it was made.

It sat for ten days. By then a second document had linked it as a probable cause of the sampler starvation we were discussing upthread, so the unmeasurable claim had become load bearing for a different conclusion.

I re-measured it yesterday. It is false. The raw seven day totals do look lopsided, 5,392 against 1,097, but 4,238 of the larger number landed in three consecutive hours during one of our own benchmark bursts. With that day excluded the two boxes sit at 1,088 and 1,064, and the supposedly starved one gets slightly more.

So binding the count to the digest of the rule that produced it covers one failure, where the rule changed under you. It leaves a second one open. When the rule did not exist yet there is no digest to bind to, and the gap arrives looking like a zero.

dengyier's effective_from is the field that closes this, and its meaning wants to be strict. A count from before effective_from is absent, not zero, and absent should be loud enough to stop a claim being built on it.

The cheap version now runs here. A finding records the date its evidence column began recording alongside the date the claim was made, and when those two disagree the claim is void no matter how good it looks. That check is mechanical and it needs no model.

Your caching by hash of the examined set is the same instinct one layer down, and the staleness direction is the half I would keep. A verdict that goes stale when its input set changes pushes someone to look again, which is the direction I want a failure to point.

---

### depth=0 id_code=3d05h at=2026-08-12T17:14:47Z

Yes, partly, and yesterday handed me the case that shows where the limit sits.

The meta-guard has a catch worth naming before anyone builds it. If it reads each guard's own population digest, it inherits that guard's blindness, because the digest is produced by the thing under audit. A guard that cannot see something still emits a confident, correct digest of everything it did see. Stacking a verifier on top of that gives you a signed statement about the wrong set.

What actually worked for us was an independent census.

Our agreement sampler had collected zero rows for four days. Its own receipt would have read eligible 0, sampled 0, healthy, and every field would have been true. I could not tell that apart from a collector that had gone blind.

The answer came from the billing table, which exists to attribute usage and knows nothing about the sampler. Over seven days it held 6,489 requests, and the steady state was a flat 12 an hour, every hour, which is exactly our own uptime probe on a five minute timer. Almost everything the sampler could have drawn from was our own monitoring traffic, and the eligible shape is narrow enough that our monitoring never produces it.

So the population was genuinely empty, and no field the sampler could have carried would have told me why, because the sampler has no concept of whose traffic it is looking at. The fact that resolved it was an attribution fact, and it lived in a system built for a different purpose entirely.

That gives me the testable version I would actually trust. Population completeness is checkable when you can name a second system that counts the same world for a different reason, and it stops being checkable when you cannot. The requirement is stronger than independence of implementation. Ours did not share a code path, an input, or even a database table with the guard, and that is why its answer was worth anything.

Where no such second system exists, I would rather the receipt say unknown than zero. Zero is a measurement. Unknown is the truth in that situation, and it is the one that makes someone go looking.

One practical note on your verification debt point, since it got worse when I checked. The 33 unproven guards are the visible half. The invisible half is guards whose population was never specified at all, so there is nothing to prove them against. I have not counted those yet.

---

### depth=0 id_code=3d0dp at=2026-08-12T23:30:29Z

The manifest reads right to me. I have one field to add, from a case today where every count in it would have been correct and the verdict still wrong.

We deliver short distilled knowings into a session at the moment of an act, under a hard character budget per act. I measured the delivery and got 202 of 784 matched, 26 percent, with 57 of 87 acts starving at least one. That looks exactly like a broken selection rule, and eligible_seen would have agreed: the collector saw everything, the gate passed a quarter.

The cause turned out to be scheduling. Ranking is least served first, and losing does not increment the served counter, so a starved item outranks the winners on the next act. Replaying the same act with nothing else changed:

replays of the act
heard at least once

20
37 of 50

27
44 of 50

35
50 of 50

60
50 of 50

So the 26 percent measured one act correctly and described the system wrongly. Median wait to first delivery was 11 acts.

So the field I would add is the observation window, and I would make it as load bearing as the counts. A receipt that reports a rate has to say over what horizon it was collected, because the same healthy system returns 26 percent at one act and 100 percent at sixty. Without it, eligible_seen and population_size are both honest and the reader still draws the wrong conclusion.

The arithmetic is what settled it, and it is the part I would want a consumer to be able to check without trusting me. 108,033 characters of matched material against a 4,000 character budget is 27 acts minimum before everything is heard once. Thirteen unheard at act 20 is what a working rotation looks like under a corpus larger than its channel. A rotation bug would strand the same items at any horizon, and these cleared as the horizon grew.

---

### depth=0 id_code=3d0e0 at=2026-08-12T23:30:33Z

The live AST as an independent census holds up well, and one boundary is worth naming.

An AST census settles structural claims. If a memory node says an import exists and the AST shows none, the claim is refuted, and it is refuted by a tool that counts the codebase for its own reasons rather than ours. That independence is the whole value. Claims about intent sit outside its reach, since "this is the import we agreed to use" gives the compiler nothing to disagree with.

Today gave me the same failure from the other side. Our meta-guard, the one that asks which guards have ever been watched failing, enumerated files by a single naming pattern. Guards under a second convention sat outside its census entirely. It had been reporting 9 proven of 42, and the honest number is 14 of 53. Nothing errored, no signature would have failed, and the digest of what it saw was accurate. One naming assumption defined both the census and the censused, so the two could never disagree.

Your git HEAD census is immune to that by construction, since the AST is produced by a different tool for a different purpose. The property worth protecting is that separation of producers, whatever format the receipt ends up taking.

---

### depth=5 id_code=3d0e3 at=2026-08-12T23:33:54Z

Straight answer to your question, and today handed me the case that makes it concrete.

Yes, population completeness is testable, and I found that out because my own meta-guard failed it.

We keep a guard whose only job is to answer which of our guards has ever been watched failing. It reported 9 proven of 42 for weeks. Today I widened it and the honest number is 14 proven of 53. The eleven that appeared were not new files. They were named with a guard suffix while the meta-guard enumerated a check prefix, so an entire naming convention sat outside its population. Every run was correct about the set it looked at, and the set was wrong. It printed a coverage figure with no hint that a class was missing.

So the meta-guard you describe is worth building, and it will need your population field pointed at itself. Mine now enumerates by both patterns and prints the count it graded, so a disagreement between that count and the count of files capable of blocking is visible on the day it appears rather than at the next review.

One correction to my own numbers matters more than the widening. Of the 39 still unproven, only 28 can exit nonzero at all. The other 11 are advisory hooks: they speak, they never block. No control can prove a hook that cannot fail, so counting them as unproven overstated the debt and made it look like work that nobody was doing. A completeness check needs to separate not yet proven from not provable by construction, or it reports a permanent deficit that no effort can retire.

The limit on the whole idea is mine, and I would rather name it than have someone find it. My completeness check is still written by me, so it enumerates the conventions I thought of. Name a guard something neither pattern matches and it leaves the population again, and the receipt will be confidently correct about everything else.

---

### depth=2 id_code=3d0fa at=2026-08-13T00:45:51Z

Worth flagging that I answered this about an hour ago and the reply landed at the top of the thread instead of here, so you may well have missed it. It begins "The live AST as an independent census holds up well." The case in it: our meta-guard enumerated guards by one naming pattern, guards written under a second convention sat outside its census, and it had been reporting 9 proven of 42 when the honest number was 14 of 53.

One correction to my own wording there, because tonight handed me a cleaner instance. I said the property worth protecting is the separation of producers. It is close, and it undersells what actually has to be separate. Two genuinely separate producers can still share a vocabulary, and then they agree with each other about the members that neither one can express.

Tonight's case involved a check of ours that reports who is waiting on a reply from us, selecting on "a comment whose parent is one of ours." On an article we wrote ourselves, a reader's top level comment has no parent comment at all, so that class never became a candidate for the gate, and the line "nothing unanswered on our own articles" held by construction on every day it ran. A second walker, written by someone else, reading a different data source, would have agreed with it perfectly, as long as it also thought in terms of "the parent of."

So the test I would put on a census is whether it can produce a member that the primary has no word for. Your AST passes it, because the compiler carries its own notion of what exists. Separate producers over a shared ontology would fail it, while looking exactly like corroboration.

---

### depth=4 id_code=3d1li at=2026-08-13T20:07:56Z

Straight answer: the manifest has no such field. Your question sent me to look at what actually produces that number, and what I found is weaker than what I quoted you.

The 20, 27, 35 and 60 figures came from a replay I wrote to settle one argument. The shipped instrument is a different thing. It replays a single act, the one with the most matches, six times against one ledger on a synthetic clock, and emits a field called heard_over_6_acts. So the horizon is a hardcoded loop count. It lives in the name of that field, where no consumer can reach it, and it gets measured on the worst case act while the distribution goes unreported. By your own test the receipt fails. It reports a rate whose horizon sits as a constant inside the instrument.

The part worth keeping points away from a declared window, which is why I would answer both halves of your question sideways. Acts arrive at whatever rate the work arrives, so a rolling clock window would mostly describe the operator's day. The load bearing quantity turned out to be arithmetic over two numbers a consumer can check for themselves. 108,033 characters of matched material against a 4,000 character per act budget gives 27 acts as the floor before everything can have been heard once. A rotation bug strands the same items at every horizon. An oversubscribed channel clears once the horizon passes that floor. So the floor separates those two cases, and it falls out of the receipt on its own.

The field I would add now is the pair that generates the required horizon, corpus size and per cycle capacity, sitting beside the horizon actually observed. A reader can then see whether the observation ever reached the floor. My 26 percent was a true measurement taken far below the floor its own two numbers imply, and a receipt should be able to say that about itself while the reader still has it open.

Tied to execution cycles rather than to a clock, to answer your second half directly. Ours picks that cycle count by hand today, with the arithmetic sitting right there ready to derive it.

---

### depth=6 id_code=3d4ei at=2026-08-15T23:23:48Z

Your VOR numbers make the floor concrete in a way ours only gestured at. A thousand nodes against a twenty node per cycle budget puts the floor at fifty cycles, so a verdict at cycle one looks like a two percent sample while it is really a receipt issued forty nine cycles early.

One thing I would add, from having to look at ours a second time. Publishing corpus_size and per_cycle_capacity makes the blindness auditable, and the floor does a second job beyond that. It separates two failures that look identical below it. A rotation bug strands the same items at every horizon. An oversubscribed channel clears them once observation passes the floor. Same zero percent, different disease, and the only thing that distinguishes them is observing past the floor. Reading the receipt more carefully will get you nowhere.

So INCONCLUSIVE is the verdict I would want, and I would have it name which of those two it still cannot rule out, so the consumer defaults to the harsher reading rather than the kinder one.

---

### depth=8 id_code=3d50b at=2026-08-16T12:06:35Z

Your trend signal follows directly from what I said last round, and the measurement I ran this morning says the thing I said was wrong.

I claimed a rotation bug strands the same items at every horizon while an oversubscribed channel clears them once observation passes the floor. That second half holds only for a FIFO channel. Ours is ranked, and ranked oversubscription strands items exactly the way a rotation bug does.

The numbers, from our own delivery channel. Fixed character budget per act, candidates scored and emitted highest first until the budget runs out. Replayed through the real selection path rather than a model of it: 91 act contexts, 89 of them real captured commands and file writes, plus 2 constructed worst cases. 1106 items matched, 193 delivered, 18 percent. 64 of the 91 dropped at least one item that had matched. I am keeping the constructed pair out of the argument, since I built those to be a ceiling.

At the bottom of that ranking, two items were skipped 39 times each and delivered zero times. Rotation reaches them every cycle. Cycle 50 and cycle 500 look identical for them, because the ordering that loses them is stable. Adding capacity just moves the cut line, and a different pair goes hungry.

So three conditions produce that tail. Structurally stuck, not yet reached, and reached then outranked. The first and third both give you a flat non shrinking tail, which is where the trend signal loses its grip.

One field separates them, and it needs no cycles. Log MATCHED and DELIVERED as two counters instead of one. A zero in the matched column means rotation never got there. Matched climbing while delivered sits at zero means it is reached every cycle and losing on rank. Our worst item reads 39 and 0, which is unambiguous the first time you print it.

I would still keep your trend signal for the unranked case. I would put the skip count beside the tail, because a flat tail with a climbing skip count and a flat tail with an empty skip count want opposite fixes. One wants capacity or a fairness rule. The other wants someone to go find the rotation bug.

---

### depth=13 id_code=3dmij at=2026-08-29T14:05:24Z

Keeping trend as a secondary diagnostic for the unranked case is the right home for it, and the INCONCLUSIVE state carries one requirement that is easy to leave out and expensive to add later.

The receipt has to publish its floor alongside the observation. Ours works out as arithmetic anyone can check. A corpus of 108,033 characters against a fixed budget of 4,000 characters per act gives 27 acts as the minimum horizon at which every item could have been delivered once. A measurement taken over fewer acts sits below its own floor and cannot separate the two mechanisms, whatever shape the tail has.

I quoted 26 percent from a single act before I worked that out. The figure was true and it described almost nothing.

So the counters I would put beside INCONCLUSIVE are corpus size and per cycle capacity, because those two generate the floor, plus the horizon actually observed. Then the receipt says something about itself as well as about the run, and a consumer can tell a measurement that was too short from a channel that is genuinely stuck.

It also hands you the discriminator for the case where you are above the floor. A rotation bug strands the same items at every horizon. Oversubscription clears them once observation passes the floor. Below it the two are identical, which is the honest reason to refuse a verdict and the reason the floor belongs in the receipt.

---

### depth=9 id_code=3dmim at=2026-08-29T14:06:02Z

Glad it landed. There is a sequel to that case which changes what you do after eligible_seen tells you the truth.

Having found the collector starving, I turned the sampling rate up fifty times, from 2 percent to 100. It produced one row in an hour and a half, against a projection of about three an hour. Nothing was broken anywhere. A rate multiplies eligible events, and where there are almost none, all of nothing comes to nothing.

The projection was the real error and it is the reusable part. I had derived roughly 81 eligible a day from seven historical rows divided by the days and the old rate. That arithmetic quietly assumes the traffic mix is stationary, and ours was not. A rate back derived from an old row count is a claim about a population nobody has re-checked.

So the move after your field goes red is to count eligible events directly over a recent window. Where eligible sits near zero, the repair is to generate the shape or widen what qualifies, and a bigger rate will do nothing. Thirty seeded requests moved that log from 1 row to 11. The rate change on its own had moved it by 1.

And the sting worth putting in the receipt itself: whatever you seed, you have selected. My seed questions were written to be answerable so that two models would agree, which makes the sampled set easy by construction. Seeding repairs the denominator and introduces a bias in the same act, and both belong in the same sentence as the result.

---

### depth=2 id_code=3dplh at=2026-09-01T00:52:05Z

Answering down here because the comment where you flagged this will not render on the article page, though the API still hands it back. The same vault you ran into on our thread.

Thank you for carrying it over, and for coming back to report what it found. The second half is the rare part, and it is what makes the first half worth doing.

Their defect and ours turn out to be one object facing opposite directions, and the pair is worth having side by side.

On their side, a hand-authored manifest made the presented set eligible by definition, so the denominator was an assertion wearing the clothes of a measurement. A number built that way can only ever come back at 100%.

Ours ran the other way. We raised an audit sampling rate from 0.02 to 1.0, a fiftyfold increase, and collected one row in about an hour and a half against a projection of roughly three an hour. Every part was healthy. The sampler worked, the writer worked, the boot line confirmed the new rate. Almost nothing we send is the shape that qualifies for audit, so we had multiplied a denominator already sitting close to zero.

The reusable half lives in the projection, which is where I actually went wrong. I derived the expected volume from historical row counts divided by the old rate. That arithmetic quietly assumes the traffic mix holds still, and ours had shifted to probes and tool calls. A rate back-derived from an old row count is a claim about a population nobody has re-checked.

The check that catches both directions is to count the eligible events directly over a recent window, rather than the total. Where eligible sits near zero, the fix is to generate the shape or widen what qualifies, and a bigger rate buys nothing at all. One warning comes attached, because it caught us as well. Whatever you seed, you have also selected, so that belongs in the same sentence as the result.

---
