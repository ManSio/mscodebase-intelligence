# OWP v0.4 Discussion Draft — «Verification must itself be verified»

> **Where this lives:** GitHub Discussion (per Brian Jin's suggestion). Source of truth for technical detail: `experiments/owp_rfc_001_v04.md` (full RFC patch with Appendices A–D).
> **Status:** Draft for discussion — not yet a formal proposal.

---

## 1. TL;DR

The OWP v0.3 spec defines the *format* of proof, but not the *mandatory behavior of the consumer* of proof. Two independent reviews (Brian Jin — Judgment Pack; Mikhail) converged on the same structural gap; two rounds of red-team attacks (10 cases) reproduced it in working code.

**Proposed v0.4 changes:**

1. **Consumer Obligations** (new normative section) — no silent soft-fail: verify revocation locally (staple) or hard-fail. Applies to agents, not just human verifiers.
2. **`retraction_staple`** — OCSP Must-Staple analog (RFC 7633): cheap, local, background-issued non-revocation proof with `max_age`. Hard-fail works because the check is local.
3. **`receipt_id` + `policy_binding` + `min_accepted_revision`** — receipts bound to the exact policy checkpoint they were issued under; replay of old revisions rejected for new claims.
4. **Negative-control hardening** — `provocation_type` (semantic pinning: digests pin bytes, not intent), `control_set_digest`, transitive fixture closure, and a **mandatory review record on re-pin**.
5. **`effective_from` disambiguation** — normative (trusted-time) vs descriptive fields.
6. **§7 wording correction** — split-view: a receipt proves consistency with the history *shown to this verifier*, not that no other history exists.
7. **Population-manifest collector trust** — `collector_witness` MUST for material claims (`eligible_seen` is self-reported; digests protect the report, not the collection).
8. **License reconciliation** before external contribution.

## 2. Why now (evidence, reproduced)

| Experiment | Result |
|---|---|
| `ln.strip()` class (assert-after-return) | buggy gate: 2/2 on good inputs, **0/3 on bad** — invisible without a negative control |
| "proven" classification | **1 → 7/40** guards depending on an undocumented threshold |
| Population manifest | `(400, 0)` broken day vs `(0, 0)` healthy idle — indistinguishable without `eligible_seen` |
| Consumer soft-fail (OCSP trap) | **36%** revoked receipts used undetected under latency pressure (soft-fail) vs **0%** (hard-fail/staple) |
| Digest-pinning | fixture edit → UNPROVEN → schema-level detection; re-pin requires a reason (review record) |

All simulations: seed-fixed, stdlib-only, parameters documented (Appendix B of the RFC). Percentages are calibration-dependent; the mechanisms are not.

## 3. Threat Model — what OWP does NOT prove (10 cases)

> «Signed receipt» ≠ «not forged». OWP proves consistency of claims with artifacts, not the truth of the world.

| # | Attack | Verdict |
|---|---|---|
| TC-1 | Control theater — digest pins bytes, not `provocation_type`; always-red control → legit "proven" | **Fixable in v0.4** (semantic pinning + review at re-pin) |
| TC-2 | Collector forgery — self-reported `eligible_seen`; compromised collector invents events | **Fixable in v0.4** (`collector_witness` MUST-when-material) |
| TC-3 | Staple race window — compromise→detection gap (22% at U(5,30)/U(0,90) params) | **Residual risk** (manage via `max_age << detection latency`) |
| TC-4 | Checkpoint stuffing — chain consistent, content malicious | **By design** (trust anchor; X.509 analog) |
| TC-5 | Split-view — two internally consistent histories | **Bounded in §6**; detection needs external witness |
| TC-6 | Issuer collusion — capability ≠ honesty of a specific run | **By design** (attestation, not proof-of-truth) |
| TC-7 | Marker substring spoof via negation | Variant of TC-1; exact/structured markers |
| TC-8 | Transitive dependency gap — edits to checker/config invisible to pin | **Fixable** (transitive fixture closure — implemented) |
| TC-9 | Policy replay — old revision replayed after upgrade | **Fixable in v0.4** (`min_accepted_revision`) |
| TC-10 | Pin-log self-attestation — review record forgeable without external anchor | By design; integrity via git/co-signer (v0.5) |

**Common root of TC-2/4/5/6/10:** the protocol has no witness/consensus layer. That is declared **v0.5 scope**, not silently implied.

## 4. Open questions for the community

1. **Soft-fail:** full ban, or permitted with mandatory `soft_fail_rate` reporting? (Must-Staple's deployment friction suggests the latter deserves a serious look — RFC 7633 §4.2.3.1 "MAY accept but MUST NOT call secure".)
2. **Staple:** who sets `max_age`? Trust model for the co-signer? Cost of background issuance at volume?
3. **`control_set_digest` registry:** public (CT-like) or per-issuer? (CT illusion: a log proves publication, not truth.)
4. **Witness layer:** external append-only witness log — v0.5, or should high-value receipts require it sooner?
5. **`min_accepted_revision`:** should old-revision receipts be rejected outright for new claims, or flagged with a configurable policy?

## 5. Requested review

- **Semantics:** is `provocation_type` the right primitive for semantic pinning, or is a structured "claim↔fixture" manifest better?
- **Consumer obligations:** does the MUST NOT soft-fail rule break legitimate degraded-mode deployments? (Our MSCodeBase implementation has an explicit fallback path for MCP-outage — we're counting it, not hiding it.)
- **Threat model:** any missing adversarial case in TC-1..10?

---

*Reference implementation: guard inventory runner (`scripts/negative_controls_runner.py`) in the MSCodeBase project — PROVEN/UNPROVEN/BROKEN classification, digest-pinning, mandatory re-pin reason, self-test. CI-verified on ubuntu/windows.*
