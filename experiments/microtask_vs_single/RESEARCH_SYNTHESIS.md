# Research synthesis — microtask_vs_single (2026-10-20)

Own synthesis. Third-party material is quoted briefly; raw dumps live outside the
repository (`%TEMP%\opencode\tom`, `%TEMP%\opencode\probe`).

Question: **what is the best confirmed design for a parent agent that delegates
to isolated one-shot microtask workers, and what must our own experiment change
before it is worth running again?**

## 1. Sources used

| # | Source | Date | Access |
|---|---|---|---|
| S1 | Anthropic, "Effective context engineering for AI agents" | 2025-09-29 | anthropic.com/engineering/effective-context-engineering-for-ai-agents |
| S2 | Anthropic, "How we built our multi-agent research system" | 2025-06-13 | anthropic.com/engineering/multi-agent-research-system |
| S3 | RouteLLM (arXiv:2406.18665v4) | 2024-06-26 / rev. 2025-02-23 | arxiv.org/abs/2406.18665 |
| S4 | Tīrtha, "Four models, one job each…" (dev.to 4879567) | 2026-10-19 | dev.to/tom_jones_230c4659491adcd |
| S5 | Tīrtha, "Serving cheap when two models agree" + CORRECTION (dev.to 4016823) | 2026-06-29, correction 2026-07-27 | dev.to |
| S6 | `Tirthahq/crystal-memory` → `docs/measured.md` | repo, pushed 2026-10-19 | github.com/Tirthahq/crystal-memory |
| S7 | `catalogue/` (21 entries) + `starter/crystal-a-positive-control-cannot-detect-a-yes-machine.md` | derived 2026-09-18…23 | same repo |
| S8 | our own pilot | 2026-10-20 | `experiments/microtask_vs_single/results_summary.json` |
| S9 | our own repo as corpus source | 2026-10-20 | 29 module+test pairs, 0.6–5.5 kB modules |

## 2. Evidence table

| Claim | Source | Status |
|---|---|---|
| Multi-agent (Opus 4 lead + Sonnet 4 subagents) beat single-agent Opus 4 by **90.2%** on an internal research eval | S2 | CONFIRMED as their measurement; research domain, not coding → not transferable without our own run |
| **Token usage alone explains 80%** of BrowseComp variance (tool calls and model choice are the rest) | S2 | CONFIRMED (published) |
| Agents use ~4× more tokens than chat; multi-agent ~**15×** | S2 | CONFIRMED (published) |
| A subagent may burn tens of thousands of tokens and return **1 000–2 000 tokens**; the lead keeps a clean context | S1 | CONFIRMED (design guidance) — matches our Brief (1 164/1 352 B) |
| "Each subagent needs an objective, an output format, guidance on the tools and sources to use, and clear task boundaries" | S1 | CONFIRMED — our Brief has goal+acceptance, **lacks explicit tool guidance** |
| Evaluate **end state**, not turn-by-turn, for agents that mutate state | S2 (appendix) | CONFIRMED — our hidden-test end-state evaluation is the right shape |
| Write subagent output to a filesystem and pass references, not payloads ("game of telephone") | S2 (appendix) | CONFIRMED — we already do (diff on disk, JSON to parent) |
| A learned router cuts cost **>2×** without quality loss and transfers across model swaps | S3 | CONFIRMED (preprint) — external anchor; note the magnitude (2×) is *below* our measured 3.8–4.7× overhead |
| `tirtha/auto` has no fixed base model: in `mode=low` the same arm was served by `Cerebras` and `deepinfra` (`gpt-oss-120b`, `Qwen3-Coder-480B`) | S8 | CONFIRMED by us, per request, in `runs/D-*/proxy_requests.jsonl` |
| "A crystal cannot help where the model is not going to make the mistake" — their holdout separated on only 1 of several scenarios across 3 model families; the rest did not replicate because the dropped arm already scored high | S6 | CONFIRMED (their own data) — **this is exactly our pilot's failure** |
| Their routine-builder pilot failed on long multi-step jobs; 0.936¹² ≈ 0.45; the real cause was a silent provider-credit fallback to a weaker model, invisible until someone read the ledger | S4 | CONFIRMED (published with two in-place updates) |
| A **positive control cannot detect a yes-machine**; always pair with a negative control; the harness must **refuse to print a score** when a control fails | S7 | CONFIRMED — adopted as a hard rule in our collector |
| A control built from the treated arm is not a control | S7 | CONFIRMED — our canary control was built that way → the isolation claim is **withdrawn**, not defended |
| An instrument that reshapes the input fabricates the test | S7 | CONFIRMED — our proxy injects `tirtha.mode=low` → we owe a **D-direct** control arm |
| A single run is noise even at temperature 0; report the **floor** and the **partition**, not the total | S7 | CONFIRMED — our 1-run cells are a smoke test; the collector now flags them |
| One calibration pair is a smoke test, not a validation; the control must travel the same path as the measurement | S7 | CONFIRMED — our hidden run silently used the repo's `pyproject.toml` as pytest config while the public run used the worktree's `pytest.ini` → **fixed** (same `-c` now) |
| A rate knob cannot fix a denominator; count the **eligible** events first | S7 | CONFIRMED — model availability: 2 of 4 probed models were eligible (the other two hung on provider errors) |
| No expected duration means no silence looks wrong | S7 | CONFIRMED — implemented `harness/probe_model.py` with a hard budget |
| Our pilot: A and D both 4/4; D spent **3.8–4.7×** the tokens of A | S8 | our measurement |

**Not verified (stated as such):** FrugalGPT, SWE-agent microagents and Aider
architect/editor numbers were not read; Tīrtha's 454 comments on other people's
posts are not enumerable through the dev.to API; Tīrtha's "verified claims
ledger" is not in the public repo.

## 3. What the research changes in our design (six forced revisions)

**P1 — The comparison must be token-matched.** 80% of the variance in the
published multi-agent result is explained by tokens spent (S2). Our D arm spent
3.8–4.7× and matched A on 4 trivial tasks; that is consistent with "more
tokens bought the same result", not with "decomposition helped". New rule: the
main run compares **A-with-budget** against **D-with-budget** (same token
ceiling), and the token ratio is reported as a first-class metric, not a
footnote.

**P2 — The corpus must contain failures.** "A crystal cannot help where the
model is not going to make the mistake" (S6) is our own pilot in one sentence:
both arms 4/4 means the instrument measured nothing. New corpus = **mutation
based on our own repo**: take a real module + its real test, seed one realistic
defect, freeze the snapshot with the diaries and KNOWN_ISSUES removed (the
agent must not read the fix), and use the module's own test file as the hidden
test. 29 candidate pairs are already enumerated (S9); 10 are selected by a
fixed rule (module < 6 kB, own test file < 14 kB, defect class from our own
P-### lessons).

**P3 — Three task classes, not one.** A yes-machine passes a corpus where every
task is "make a change" (S7). New classes: (a) **fix** — a seeded defect, the
correct answer is a patch; (b) **no-op** — nothing is broken, the correct answer
is to change nothing (a "fixer" that always edits must fail); (c) **legitimate
block** — the request is under-specified, the correct answer is `blocked`, and a
plausible wrong patch must be rejected. Each class gets its own hidden checks;
the corpus is invalid unless (b) and (c) exist.

**P4 — Two controls the harness was missing.**
*Instrument control (D-direct):* our proxy rewrites the request body, so the
D arm measures "OpenCode → our proxy → Tīrtha", not "OpenCode → Tīrtha"
(S7). New arm: the worker talks to `api.tirtha.ai` directly, no proxy, no
injected fields — implemented as `--transport direct`.
*Corpus control:* per Tom's method, three paraphrase controls that must hit and
three out-of-domain controls that must return NONE — applied to our *corpus*,
not only to the catalogue.

**P5 — Report the floor and the partition.** ≥2 runs per cell; the cell verdict
is the **worst** run, and the report must show which tasks the arms disagree on
(S7). The collector now does this and flags single-run cells as smoke tests.

**P6 — Refuse to print a score when a control fails.** The hidden-test
instrument is validated by a negative and a positive control before any table
is printed; an empty population is a refusal, not an empty table (§19.6, S7).
Implemented in `harness/collect_results.py` (exit 2 on a failed control or an
empty population).

## 4. The redesigned experiment (to be pre-registered before the next run)

| Element | Decision |
|---|---|
| Arms | A (single session) · C (microtasks, worker = same model as A) · D-proxy (worker = Tīrtha mode=low) · D-direct (control for our instrument) |
| Task classes | fix / no-op / legitimate-block, 10 tasks total, from our own repo (mutation-seeded) |
| Runs | 2 per cell (floor + partition reported) |
| Budget | identical token ceiling for A and C; D's overhead reported, not hidden |
| Worker contract | objective + allowed file + acceptance command + **explicit tool guidance** (S1) + JSON output schema |
| Delivery | artifacts on disk; parent reads the diff, not the transcript (S1, S2) |
| Evaluation | task-scoped hidden tests, same pytest config as the public path, end-state only |
| Attribution | every request records the model that actually served, the mode, the escalation flag and the usage; a silent model swap is an alarm (S4) |
| Step budget | per-microtask step cap and a repeat-failure escalation rule (S4's lesson: 12 steps at 0.936 ≈ 0.45) |
| Stop conditions | any control red → no score printed; D-direct and D-proxy disagree → the instrument is the suspect, not the architecture |

## 5. Why this is the "best confirmed" answer

The design now has independent support from three sources that do not share a
line of code: Anthropic's production multi-agent system (orchestrator + bounded
subagents, end-state evaluation, filesystem artifacts, token-matched
comparison), Tīrtha's own published ledger (a note cannot help where the model
would not fail; a positive control cannot detect a yes-machine; record the model
that actually served; an instrument that reshapes input fabricates the test),
and our own pilot (bounded briefs work; the corpus was too easy; the proxy is
part of the treatment and must have a control arm).

The part that is **not** confirmed: that decomposition beats a single session
for *coding* work at matched budget. Nobody we read has measured that — the
90.2% figure is for breadth-first research (S2), and Tīrtha's closest
experiment failed on long multi-step jobs (S4). Our own main run is the
measurement that would settle it, and it must be token-matched to be worth
anything.
