# Mechanical Orchestration Without LLM — Research & Tool-Boundary Recommendation

Status: 🟡 Research-only session (no src/ changes). Evidence in `EXPERIMENTS_LOG.md` (Exp M1–M3) and `AGENT_DIARY.md` 2026-08-25.

## 1. Detective pass over `experiments/rehenie.md` (claim-by-claim)

| Claim in rehenie.md | Verdict | Evidence |
|---|---|---|
| "roam-code by Dimitris Cranot, Apache 2.0" | ✅ real, ⚠️ URL wrong | Exists: `Cranot/roam-code` (511★, Python, Apache-2.0, pushed today). NOT `codeguidefx/roam-code` (404). |
| roam-code: 28 langs, task compiler, verify gates, Health Score, ChangeEvidence | ✅ CONFIRMED | README (GitHub API): 286 commands, 245 MCP tools (17 in default `core` preset), 8 presets, compiler A/B: −83% turns / −80% input tokens / −63% cost (41 cells), `ask` = deterministic router over 31-recipe registry, post-edit Stop-gate fail-closed, signed ChangeEvidence (HMAC run ledger). |
| "Agent does 8–15 calls → 1 call; ~11s → <0.5s; 15k → 3k tokens" | ✅ matches roam-code's published benchmark | Same numbers in roam-code README (Flask 200-file repro, "Tool calls 8→1, wall ~11s→<0.5s, tokens ~15k→~3k"). rehenie.md did not attribute them. |
| "Hide 85% of tools, show 5–8 meta-tools" | ❌ REFUTED | The market leader ships *more* tools than we do (245) and still wins — the mechanism is **presets + on-demand expansion + deterministic routing**, not hiding. arXiv 2605.24660: fixed-shortlist-5 loses to adaptive (87.1% vs 93.1%); depth must expand on hard queries (up to 50). |
| "Accuracy 85%→40% with 50+ tools"; "error 15%→60%" | 🟡 direction real, numbers unattributed | Tool-space interference is real (arXiv 2605.24660: decision accuracy degrades with shortlist size; medium queries 76.8% vs 60.9%). The exact percentages in rehenie.md are uncited — treat as illustrative, not measured. |
| "3,300+ calls to 14 LLMs, benchmark done" | ✅ CONFIRMED in-repo | `EXPERIMENTS_LOG.md` 2026-08-14/15/16: live-arms on OpenRouter across qwen3.5/3.6/3.7/3.8, glm-4.7/5.2, deepseek-v4 flash/pro, nemotron nano/lightning, claude-sonnet-5 — 3300+ calls, per-model recall/FA tables. |
| "30–70ms for 7 parallel passes" | ❌ NOT reproduced in our stack | Our real matrix: search_code(fast) 75ms ✓, search_code(quality) 3666ms ✗ (semantic miss), get_symbol_info "not found" on a real symbol (2nd miss/session), grep 28ms. roam-code compile ≈90ms is their measured number; ours is slower because vector path is heavy. |
| Aider repomap (PageRank on AST) | ✅ repomap real | Aider README: "Aider makes a map of your entire codebase", 100+ languages (ctags/tree-sitter); PageRank-style ranking per its repomap docs. |
| 4 blind spots (git blame, config/env, shadow coupling, token budget) | ✅ all real | Confirmed as gaps in our stack: no co-change matrix wired into search; token budget only in search limit; config/env not in context compile. |

## 2. Real-data results (this session)

- **Telemetry (M1):** 62 tools registered (32 core + 14 intel + 12 inline + 4 dev); server masks 16/32 by default; only 5 tools *ever* recorded metrics (8 calls, 3 errors — LSP toolkit 37.5% error rate, 15s timeouts). Long tail of dead tools is unmeasurable — no per-call counter logging.
- **Sub-agents (M2):** natural agent → **0/5 MCP calls** (list_directory/read/edit/terminal only); MCP-first agent → 9 calls, ~4 wasted on unindexed files (search×2, get_symbol_info, find_path misses); productive = passport/status + read_live_file×3. New files are invisible until reindex.
- **Latency matrix (M3):** fast 75ms ✓ vs quality 3666ms ✗ vs grep 28ms ✓ vs get_symbol_info ✗ "not found".

## 3. Recommendation: the tool boundary (what to actually build)

1. **Default visible set: ~8–12 tools** (job-shaped, not atom-shaped): one search (fast-first cascade), one read, one context-compile, one impact/verify, one runtime status, one change-preview. The remaining ~50 go into **presets / explicit `expand_toolset`** (roam-code pattern), not deletion.
2. **Mechanical cascade inside composite tools (no LLM):** exact (ripgrep/FTS) → LSP/disk read → vector only as last resort, with per-stage QoS budget (e.g. abandon vector >1.5s). On unindexed/fresh code → disk read + ripgrep with honest `source=disk` status (M2 failure).
3. **Deterministic intent router** over a recipe registry (~30 recipes, like roam `ask`): keyword/symbol-name/filename signals, tuned on our own 3300-call corpus — NOT an LLM classifier.
4. **Per-call tool telemetry** (counter per tool in the error_handler path) — the boundary is unmeasurable without it (M1).
5. **Fail-closed post-edit gates** (import firewall, delete-check, secrets) with symbol-keyed suppression (roam-code precedent) + gate-precision corpus in CI.
6. **Prompt/discoverability matters more than tool count:** M2 shows instruction about MCP flips usage 0→9. Ship a short "when to use which of the 8 tools" block in AGENTS.md/AGENT_DIARY deployments.

## 4. Red Team on the proposal

1. **Attack: fresh/unindexed target → semantic layer silently empty → agent wanders (measured in M2).** Defense: composite tools return `source=disk|index` and auto-fallback to ripgrep/diskk reads; a "reindex needed" hint with estimated cost; regression test = M2 scenario in CI.
2. **Attack: deterministic router misroutes query → wrong recipe.** Defense: cascade by cheap exact signals with a generic-context fallback recipe; keep a labeled misroute set (from 3300-call corpus) and re-run on every recipe change; never make routing fail-closed (a bad recipe is worse than a generic context).
3. **Attack: fan-out output bloat → 200k tokens (rehenie.md's own blind spot).** Defense: hard output budget + truncation policy (names-only beyond depth N) — token-budget test per composite tool; cap vector stage contribution.
4. **Attack: fail-closed gates reject good edits (precision loss).** Defense: symbol-keyed suppression file (like `.roam-suppressions`), gate-hit logging with weekly precision review; suppressor cannot alter gate policy/baselines.
5. **Attack: parallel agents × composite tool → shared LanceDB lock (real 2026-08-25 freeze incident).** Defense: keep reindex fast-fail + `asyncio.to_thread` in every new fan-out path; stress-test N=2 and N=8 concurrent compiles asserting *correct association* of results (caller A gets A's symbol), not just no-exception.

Verdict: plan is workable with defenses 1–5; largest open risk is (2) routing precision and (3) token budget — both measurable before implementation.