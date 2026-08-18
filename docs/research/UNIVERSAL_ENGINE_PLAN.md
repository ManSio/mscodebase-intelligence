# Universal MCP Engine — Detailed Implementation Plan

> Companion to the ТЗ «MSCodeBase Intelligence → Universal MCP Engine» (L1-656,
> owner draft, filename: MSCODEBASE_UNIVERSAL_TOR.md).
> Produced 2026-08-18. Every claim about the current codebase was verified by
> reading the code this session; every external fact was verified by live fetch
> (URLs inline); local experiments E-01/E-02 were run this session (raw output
> in the experiment log below).
> Language: English per owner protocol §0.-2 (RU translation available on request).

> **STATUS 2026-08-18 (evening):** Фаза 0 + Фаза 1 executed on
> `feat/universal-engine` (commits 7232a6e2, cb8f671f, 55a2af41): Windows/Zed
> extraction, gate, plan docs, ledgers. Фаза 1: `src/sources/` created,
> WorkspaceSource Protocol in core interfaces, LocalFsSource (resolve/watch/
> fingerprint), Indexer consumes the source (path_manager from LocalFsSource),
> helpers' final home = src/sources/local_fs/windows.py, adapters/local_fs deleted.
> 1308 tests green. Not pushed (owner command pending).

---

## 0. Executive decisions (asked by owner: build-from-0 vs migrate; new folder vs in-place)

### D-1. MIGRATE in place. Do NOT build from scratch. Evidence:

| Claim in ТЗ | Verified state in repo (this session) | Implication |
|---|---|---|
| `src/mcp/server.py` = "imports + registration" | True — thin facade, re-exports, `create_mcp_server()` only registers | Transport extraction is low-risk |
| DI container exists | `src/core/di_container.py` — `ServiceCollection` (add_singleton/resolve) | ToolPlugin `register(container)` has a home |
| Tools are constructor-injected classes | `MCPTool` ABC in `src/mcp/tools/base.py` (name/execute/resolve_indexer), 47 `tool_name=` registrations in `tools/*.py` | Plugin protocol = wrapping, not rewriting |
| `verify_action` exists | `VerifyActionTool` in `lifecycle_tools.py` + `ExecutionContract` in `src/core/execution_contract.py` | Action Receipt (§11) builds on existing code |
| `before_hash`/`after_hash` exist | `ChangeIntent` (execution_contract.py:96-117) already records both + `base_commit` + `ChangeIntentLedger` (JSONL in data_root) | §11 foundation is 80% present |
| `ProjectIndexerRegistry` LRU(5) | `src/core/indexing/project_indexer_registry.py` | Reusable for remote cache (ТЗ rec. 2) |
| Rate limiter + circuit breaker | `src/core/rate_limiter.py` — `SlidingWindowRateLimiter` + `CircuitBreaker` | Reusable for remote gateway (ТЗ §3.2) |
| Windows-specific path code | `src/utils/paths.py` (`SafePathManager`, `to_win_long_path`) — imported by db_manager, intelligence tools | Extraction target for Фаза 0; note: it's already in `utils/`, not core |
| Zed-specific config | `src/utils/zed_config.py` (patch_zed_settings etc.), `extension.toml`, `src/main.py` (Zed-first entrypoint with `--install-global`) | Extraction target for Фаза 0 |
| Tests | `pytest tests/` = 1398 (diary 2026-08-18); `scripts/smoke_e2e.py` live-check exists | Safety net for behavior-preserving refactor exists |

The engine's value is 47 tool classes + 18 intel tools + Indexer/Searcher/SymbolIndex
+ IntelligenceLayer — 1.5 years of tested code. The ТЗ itself says core does not
change; only the surround changes. A rewrite would discard the safety net for no gain.

### D-2. One repo, one feature branch, new packages INSIDE the tree — not a parallel project folder.

- **Phases 0-1** (behavior-preserving refactor): in-place in `D:\Project\MSCodeBase`.
- **Phases 2+** (new subsystems): new package dirs inside the SAME repo, developed
  behind the existing tree, wired through DI, verified by the existing 1398-test
  suite + `smoke_e2e.py` on every merge:
  - `src/sources/` (WorkspaceSource: local, git_url, upload)
  - `src/mcp/transport/` (stdio stays, streamable_http added)
  - `src/plugins/` (ToolPlugin protocol, gate, loader)
  - `adapters/` (zed/, vscode/, claude_code/, cli/) — config + thin glue, mostly non-code
- **Experiments only** go in `experiments/universal-engine/` (throwaway probes;
  `experiments` already excluded from pytest collection via `norecursedirs`).
- Work happens on branch `feat/universal-engine`; each phase is a PR against main
  (§0.-3: main is protected, PRs only).

Rationale: a full parallel copy doubles maintenance and orphans the existing test
harness; a pure in-place refactor of everything risks the exact regressions the ТЗ
warns about. New dirs inside the tree give the "build-and-verify in a new place"
property the owner asked for, without forking the core.

### D-3. Interactions from all sides (the "multi-" problem, ТЗ §9б extended)

| Axis | Scenario | Owner | Solution |
|---|---|---|---|
| Multi-window (same editor, same project) | 2 Zed windows → 2 stdio processes | `adapters/zed/` | Already solved (PID-lock, port-ready dedup, CWD-first resolve). Stays in adapter. |
| Multi-project (different projects) | Zed on repo A + VS Code on repo B, or 2 remote workspaces | **core** | `ProjectIndexerRegistry` (LRU(5)) moves from "Zed-triggered" to core abstraction. It never was Zed-specific; only its trigger was. |
| Multi-client, one remote HTTP server | 2 clients hit same workspace via HTTP+SSE | **core (new)** | Shared read (reuse index cache). Concurrent write → workspace-level lock (generalize PID-lock self-healing from process→workspace). Write to remote = read-only by default (ТЗ rec. 3). |
| Multi-editor on same project (local) | Zed agent + VS Code agent edit same files | **core** | `notify_change` DebounceBatch dedup per client; LanceDB write serialization already via `DatabaseLock`; cross-process index race covered by existing lock+guard; verify with new E-10 stress test. |
| Multi-OS | Windows dev + Linux CI + macOS | adapters | Фаза 0 moves `SafePathManager`/`to_win_long_path` into `adapters/local_fs/windows.py` (no-op on POSIX); CI matrix runs tests on ≥2 OSes from the FIRST Phase-0 PR (ТЗ §9б-8). Python 3.10 EOL 2026-10 → matrix is 3.11/3.12/3.14. |
| Plugins | third-party code inside our process | **core (new)** | Trust gate + hash-pin + subprocess isolation (see §5). |

---

## 1. Section-by-section plan (mirrors ТЗ 0-12)

### §0 Problem — verdict
Confirmed on all three counts: OS coupling (paths.py Windows code imported across
core), editor coupling (extension.toml + zed_config.py + main.py Zed-first), and
local-only source (no URL path; `resolve_project_root` is disk-bound). The three-axis
split (§1) is the right decomposition. No changes to this section.

### §1 Three axes — architecture
Adopt the diagram as-is. Concrete contracts:
- `WorkspaceSource` (Protocol) — new `src/sources/`; consumed by Indexer factory and
  `resolve_indexer_for_request` (base.py:100) so tools keep working unchanged.
- `Transport` — `src/mcp/transport/`; the 47 tool classes never touch it (verified:
  they take `ServiceCollection` only).
- `Adapter` — `adapters/`; extension.toml/settings/install split per editor.

**Attack R-1 (axis bleed):** a tool reaching past its layer (e.g., `read_live_file`
importing `platform_utils.get_zed_*` after refactor). Guard: layer-boundary test —
`grep -rn "get_zed\|to_win_long_path\|platform.system" src/mcp/tools/` must be empty;
add a CI gate (extend `scripts/check_tool_names.py` pattern).

### §2 SOURCE LAYER — WorkspaceSource

#### 2.1 LocalFsSource
Wrap current path normalization (paths.py) with NO behavior change. Windows path
handling moves to `adapters/local_fs/windows.py` (Фаза 0); Linux/macOS = no-op.
DoD: `pytest tests/` = 1398 unchanged; smoke_e2e passes.

#### 2.2 GitUrlSource — researched + measured (E-02)
Prior art verified live: bloop (bare-repo clone-to-cache via gitoxide, pull-or-reclone
on failure, per-repo shallow depth — archived 2025, closest design match);
Sourcegraph gitserver (schedule/queue, `gitMaxConcurrentClones`,
`gitMaxCodehostRequestsPerSecond`, 45s–8h poll bounds); searchcode.com (server-side
fetch, SSH/token auth for private repos, no published cache policy); Bazel disk-cache
GC (max-size + max-age + idle sweep — the only published implementation of our exact
eviction knobs). OWASP SSRF cheat sheet + GitLab webhook hardening (DNS-rebinding,
block RFC1918/IMDS) are the security baseline.

Design (each item has an E-experiment or citation):
1. **Scheme allowlist before git ever sees the URL:** `https` only. Reject
   `ssh://`, `git://`, `file://`, scp-like `host:path`, userinfo/credentials in URL.
   *Measured:* `git clone file://...` exits 128 by default (git ≥2.38 CVE-2022-39253
   fix) — but we do NOT rely on that; we reject at parse time. (E-02d)
2. **Domain allowlist** (github.com, gitlab.com, bitbucket.org + configurable
   self-hosted). Not a denylist (OWASP: deny-lists are bypass-prone).
3. **DNS-rebinding defense:** resolve host → collect ALL A/AAAA → reject if ANY is
   non-global (127/8, ::1, 0.0.0.0/8, RFC1918, link-local, multicast, IMDS
   169.254.169.254, metadata hosts). Re-verify after redirects (git smart-HTTP
   follows redirects) — treat final host as untrusted.
4. **Clone runtime hardening:** `-c protocol.file.allow=never -c protocol.ext.allow=never`,
   no `--recurse-submodules` by default (submodules = arbitrary-clone vector,
   CVE-2022-39253 class; GitHub storage doesn't recurse them either).
5. **Limits (hard, process-level):** clone timeout (default 120s), post-clone size
   cap (`du`, default e.g. 500MB) + file-count cap (e.g. 200k) → abort + evict;
   per-host concurrency limit (Sourcegraph precedent). One link to a 50GB monorepo
   must not take the server down (ТЗ §9б-4).
6. **Clone shape:** `--depth=1 --single-branch` by default (fastest tip;
   re-clone-on-major-drift instead of fetching forever — avoids the
   shallow-fetch-is-expensive trap); `--filter=blob:none` as an option when
   history-walkable indexes are wanted. *Measured (E-02b):* requests full clone 19MB
   vs blobless 7.7MB, 2.9s, tree has 130 files. Server may deny the filter → keep
   the post-clone size cap regardless.
7. **Cache:** bare-or-normal clone at `<data_root>/repos/<hash8>/`; eviction LRU(5)
   + TTL 24h (ТЗ rec. 2 — same number already proven for multi-window), size-bound
   + idle sweep (Bazel disk-cache GC pattern); never evict a source with an
   in-flight index job; evict index shards + manifest atomically.
8. **Fingerprint / cold-start:** use git's own Merkle tree — `git rev-parse HEAD` +
   `git ls-tree -r HEAD` = manifest of (path → blob-oid) at near-zero cost.
   *Measured (E-02):* 79ms for the whole tree, zero content re-hashing. Store
   `{last_indexed_oid, manifest}`; on re-check diff manifests → re-embed only
   changed paths (this realizes the simhash cold-start idea from DEV_EXP §11 —
   correctly: exact Merkle for skip logic; simhash/ssdeep ONLY for near-duplicate
   decisions like fork detection, never for skip logic).
9. **Incremental pipeline (TOCTOU-safe):** fetch → pin tree OID → diff vs stored
   manifest → embed changed → update manifest+OID last. Work against the pinned OID
   (Bazel's `--experimental_guard_against_concurrent_changes` precedent). On
   mismatch/corruption → full re-embed; on pull failure → re-clone (bloop pattern).
10. **INCONCLUSIVE, not crash:** nonexistent repo / private-without-token / timeout /
    size-over-limit → `INCONCLUSIVE` verdict with reason, never a hard crash and
    never a silent success. *Measured (E-02c):* `git clone` of a nonexistent URL
    exits 128 with a clean fatal message — map that to INCONCLUSIVE.

**Attack R-2 (SSRF redirect):** allowed domain redirects to `http://169.254.169.254/`.
Defense: redirect re-validation (final-host check), and `http.*.extraheader`/env
restrictions as second layer. Test: E-08 (redirect + rebinding probe with a local
mitm or a public redirector to a private IP; run only against our own test host).

**Attack R-3 (tar/zip upload):** `UploadSource` — archive size cap before extraction,
per-file + total limits, path-traversal guard (reject `../` and absolute members),
decompression-bomb protection (zip-bomb / tar 9-petabyte sparse). TTL cleanup (ТЗ
2.1 table: KI-110 precedent — 2481 junk folders, no GC). Fingerprint = content-hash
of archive → identical re-upload skips re-embedding.

#### 2.3 Remote file access
- **Read:** `read_live_file` — extend to resolve through `WorkspaceSource.resolve()`
  (verified: it currently reads from the local project path; making it source-aware
  is a small, well-tested change). Works identically for local and cloned-remote.
- **Write:** remote = read-only by default (ТЗ rec. 3: per-workspace flag
  `--allow-remote-write`, not global); every write through the existing
  `verify_action` gate (ExecutionContract) + first-write-of-session explicit
  confirmation for remote sources.

### §3 TRANSPORT LAYER — decided: Streamable HTTP, SDK provides it

Live facts (fetched this session):
- Current MCP spec revision 2026-07-28 defines exactly two bindings: stdio and
  **Streamable HTTP**. HTTP+SSE (2024-11-05) is **deprecated** since 2025-03-26
  (SEP-2596), eligible for removal. Do NOT build new SSE work.
- Our pinned `mcp==1.28.1` (pyproject verified) is the **v1.x maintenance line**
  and ships `streamable_http.py` (`StreamableHTTPServerTransport`,
  `StreamableHTTPSessionManager`), `transport_security.py` (Origin/DNS-rebinding
  validation middleware), and an `auth/` package (OAuth 2.1 resource-server hooks).
  Verified in the installed venv: `mcp.server.sse` and `mcp.server.streamable_http`
  both present. FastMCP: `mcp.run(transport="streamable-http")` or
  `mcp.streamable_http_app()` → Starlette ASGI app (mount into our own FastAPI/Starlette
  app alongside `/healthz`).
- Client configs for remote servers are solved and verified: Claude Code
  (`"type": "http"`, headers/oauth), VS Code `.vscode/mcp.json` (`"type": "http"`,
  bearer or OAuth browser flow, HTTP→SSE fallback), Zed settings.json
  (`context_servers` with url + Authorization header or OAuth prompt). Cursor
  (community bridge configs; native page client-rendered — marked unverified).
- No spec-standard health endpoint exists; precedents are ad-hoc (`/healthz` in
  supergateway, `/status` in mcp-proxy). We ship our own `/healthz` + Docker
  HEALTHCHECK/systemd.

Plan:
1. `src/mcp/transport/stdio.py` — move current stdio wiring (behavior-identical).
2. `src/mcp/transport/streamable_http.py` — wrap `StreamableHTTPServerTransport`
   around the same `create_mcp_server()` result (same tool set, same DI).
3. `src/remote_main.py` — entrypoint: FastAPI/Starlette app, mount streamable HTTP
   + `/healthz` + auth middleware. Auth v1: **Bearer token**
   (`MSCODEBASE_REMOTE_TOKEN`), simplest, supported by all four clients. OAuth 2.1
   AS (RFC 9728 metadata, PKCE) deferred as opt-in v2 — the SDK has the hooks;
   the AS endpoints are the real work.
4. Reuse `SlidingWindowRateLimiter` + `CircuitBreaker` at the gateway (per-token +
   per-IP), not new code (ТЗ §3.2). Note: `threading.Lock`-based limiter is
   loop-agnostic (WISDOM: asyncio.Lock deadlocks cross-loop) — keep threading primitives.
5. Observability: structured logging to `data_root/logs` (already the pattern) +
   `/healthz` for uptime monitors (ТЗ §9б-6). Optionally OTel trace-context
   propagation (SEP-414) — later.
6. Deployment: Docker image + compose modeled on the official
   `example-remote-server` (separate AS pattern, Redis sessions — we skip Redis
   until multi-instance is real); update story = stop→update→start for v1, rolling
   restart documented for later (ТЗ §9б-7).

**DoD (§7 Фаза 3):** transport-equivalence test suite — same request over stdio and
HTTP returns identical JSON for a representative subset of tools (E-07).

**Known risk (must test, E-07b):** spec pushes stateless JSON-response mode for
scalability, but our engine is stateful (indexes, background jobs, sessions).
Verify what breaks (notifications `notifications/message`, background-task
progress push) before committing to stateless mode.

### §4 ADAPTER LAYER

Confirmed: DI container, 47 tool classes, Indexer/Searcher/SymbolIndex,
IntelligenceLayer know nothing about Zed (verified by reading base.py + tools).
Zed-specific things to move (Фаза 0): `src/utils/zed_config.py` →
`adapters/zed/zed_config.py`; `extension.toml` → `adapters/zed/`; `src/main.py`
install/configure modes → `adapters/zed/install.py`; `core-install` (venv, deps,
models) stays engine-level.

New adapters are config-first (ТЗ §4.3 table confirmed by client-config research):
- VS Code/Cursor: `.vscode/mcp.json` with stdio command (and `"type": "http"` for
  remote) — config + doc only.
- Claude Code/Desktop: `.mcp.json` (`"type": "http"` or stdio `command`) — config + doc.
- CLI: thin wrapper `mscodebase-cli <tool> [args]` calling tool classes directly
  (no MCP protocol) — for CI/scripts; ~1 file.
- Remote: `remote_main.py` + Docker (see §3).

### §5 PLUGIN MODEL — RCE is the #1 risk; design is trust-gate + isolation

**Attack E-01 (run this session, raw output below):** naive loading of an external
`.py` plugin (the literal ТЗ §5.2 proposal) = **arbitrary code execution in the
server process at startup** — demonstrated: plugin wrote a marker file with its pid.
Mitigated flow (trust gate before import + sha256 pin per plugin+version) blocked
it; hash-drift detection re-prompts on modification. Also notable: our own
`validate_code` sandbox (execute_script) already blocks
`importlib.util.module_from_spec` — a hint of what the AST gate can do, but the MCP
process must not rely on it for plugins.

Research grounding (fetched live): VS Code 1.97 install-time publisher trust prompt
+ signature verification (marketplace-signed; failure blocks install); VS Code
Workspace Trust (Restricted Mode disables extensions/agents/terminal; trust record
is **per extension version**); Zed extensions are Wasm-sandboxed by construction and
MCP servers run **out-of-process**; RestrictedPython is explicitly "not a sandbox";
Home Assistant requires `version` in custom-component manifests; npm engines/os/cpu
fields + `--ignore-scripts`; WordPress `Requires at least`; official MCP registry is
the future distribution path (Zed is deprecating its own MCP-server extension format
for it).

Design:
1. **Manifest** (`ToolPlugin`): add to the ТЗ's protocol:
   - `requires_engine_version` (npm/VS Code `engines` semantics — enforce at load,
     block with message on mismatch; this closes ТЗ §9б-5)
   - `schema_version` (Zed pattern — manifest evolution ≠ engine incompatibility)
   - `version` MANDATORY for external plugins (HA rule)
   - `platform` (npm os/cpu precedent — fail loudly, not silently)
   - `dependencies` (pinned; the hidden RCE surface — a plugin's `import requests`
     executes requests' code too; scan with pip-audit-style check at install)
   - Manifest maps 1:1 to an official-MCP-registry entry later; do NOT invent a
     parallel distribution format (research: mcp-get/Smithery schema precedent).
2. **Load gate (strict order, TOCTOU-guarded):** parse manifest (no execution) →
   validate schema/version/platform → verify pinned sha256 → trust record exists?
   (no: PROMPT user with name/version/publisher/sha256/source, persist per
   plugin+version; yes: proceed) → import. Any file change between gate and import
   re-runs the gate (hash the file right before import).
3. **Default-deny:** plugins do not auto-load on first run (Zed worktree-trust
   pattern); a new plugin = explicit user decision; "load but disabled" state
   (VS Code Restricted Mode pattern).
4. **Isolation boundary:** third-party plugins run in a **subprocess** (JSON-RPC or
   mini-MCP over stdio — the ecosystem-native model; even Zed runs MCP servers
   out-of-process). In-process loading only for first-party/vendor-reviewed plugins.
   RestrictedPython only as hardening for trusted-ish code, never as the boundary.
   `wasmtime` is a true sandbox but forces Wasm authors + monthly breaking majors —
   defer.
5. **Self-check registration (P-001, ТЗ §6.7):** after `container.register()` for a
   plugin, verify the tool actually appears in DI with its declared `requires`; a
   plugin that "imported without exception" but didn't register = load failure with
   reason, not silence.
6. **Signatures:** hash-pinning now (PyPI ships no per-file signatures — verified
   `has_sig: false`); sigstore/DSSE later if/when we publish to a registry (npm
   `audit signatures` precedent).

**DoD (§7 Фаза 4):** at least one third-party plugin as PoC — e.g., the VOR
`verify_claim` tool from experiments 1-L/2E extracted as a plugin. Regression tests:
E-01-style RCE negative controls in `tests/test_plugins.py` (naive-load blocked,
trust-gate works, drift re-prompts, version mismatch refuses to load).

### §6 Experiment lessons → architecture (each is a code rule, not advice)

| ТЗ ref | Rule | Implementation |
|---|---|---|
| 6.1 | LLM calls return evidence (real code fragment around anchor), never bare tokens | Extend `intel_predict_root_cause`/`generate_chunk_summaries` to always attach `evidence` (file:lines + fragment). Recall 0.08→0.88 is ours (Exp 1-L). |
| 6.2 | Manifest anchoring — closed world, not grep | `pkg:` anchor type resolving pyproject.toml/package.json/lockfile via parser, not free grep (ADR-0005, exp-3: 7 false REFUTED → 0). |
| 6.3 | Subject-identity check (present-trap, KI-103) | Verify tools must resolve anchor → AST entity via SymbolIndex/Call Graph, then scope evidence to that entity's real edges. `graph_context_first` formalized. |
| 6.4 | Every new evidence format → blind control | DoD entry for any PR touching the evidence layer: blind probe (with vs without) before default. Enforce via PR checklist in CONTRIBUTING. |
| 6.5 | INCONCLUSIVE as first-class verdict | Extend GRACEFUL_DEGRADATION 4 levels to source/transport/adapter layers (verified: exists for embedder). Source/plugin failures → degraded status with reason, not crash/silence. |
| 6.6 | Routing determinism | Only when external LLM provider appears: `pin_provider` + `allow_fallbacks:false` + K≥3 (from OpenRouter CSV audit). Not now. |
| 6.7 | P-001 guard for plugin loading | See §5.5 self-check registration. |

### §7 Phases 0-5 — task breakdown with DoD

**Фаза 0 — Separation without behavior change.**
- Move `SafePathManager`/`to_win_long_path` → `adapters/local_fs/windows.py`
  (POSIX = no-op). grep-0 for direct imports in core (CI gate).
- Move `zed_config.py`, `extension.toml`, Zed install/configure paths →
  `adapters/zed/`. `src/main.py` keeps only engine entry + adapter dispatch.
- Split `install.py` → `core-install` (venv, deps, models — engine-level) +
  `adapters/<editor>/install.py`.
- DoD: 1398 tests pass unchanged; `verify_clean_state.sh` on Windows AND first-time
  Linux/macOS; CI matrix ≥2 OS from the first PR (§9б-8); smoke_e2e live-check.

**Фаза 1 — WorkspaceSource abstraction.** ✅ **DONE 2026-08-18 (branch feat/universal-engine).**
- `WorkspaceSource` Protocol + `FileChangeEvent` → `src/core/interfaces/workspace_source.py`
  (core-owned, IEmbedder pattern). ✅
- `src/sources/local_fs/` — `LocalFsSource` (resolve/watch/fingerprint); helpers' final
  home `src/sources/local_fs/windows.py`; `adapters/local_fs/` deleted. ✅
- Indexer accepts `source: WorkspaceSource` and takes `path_manager` from it
  (default LocalFsSource; default construction moves to DI/registry in Фаза 2). ✅
- Gate: transitional core→src.sources.* = 3 (db_manager, indexer, tools_reg),
  target 0 by end of Фаза 2. ✅
- Tests: tests/test_local_fs_source.py (8) + full pytest 1308 passed / 10 skipped. ✅
- DoD: server behaves identically through the new interface (1308 green).

**Фаза 2 — GitUrlSource.** Per §2.2 design. DoD (ТЗ): 5-10 public repos of varying
size, measured clone→index (E-03); failure cases (private without token, nonexistent
URL) → INCONCLUSIVE not crash (E-02c already shows git exits 128); SSRF suite
(E-08); fingerprint skip test (second clone re-embeds 0 files — E-02 measured the
79ms fingerprint cost).

**Фаза 2.5 — private repos** (ТЗ rec. 1: after public path has ~2 weeks clean):
SSH keys/tokens stored only in OS keychain or `.env` (never in URL/disk cache),
same allowlist + limits. Secrets-leak review gate (shadow-canary precedent: 5/5
attacks passed before fix — new code is systematically leaky until proven otherwise).

**Фаза 3 — Streamable HTTP transport** per §3. DoD: transport-equivalence suite
(E-07), auth (Bearer), rate limiting reuse, `/healthz`, Docker image.

**Фаза 4 — Plugin manifest** per §5. DoD: PoC plugin (VOR `verify_claim` extracted),
RCE negative-control tests, version-mismatch tests, trust-gate UX.

**Фаза 5 — Adapters** per §4. DoD: manual verification on real VS Code/Cursor with
a real repo; CLI wrapper; docs for Claude Code.

### §8 What NOT to do — confirmed
- No Indexer/Searcher/SymbolIndex rewrite (verified clean: DI, tests, separation).
- No multi-tenant SaaS (auth per-user, isolation, billing — separate project).
- No parallel non-MCP plugin format; MCP is the standard (research: even Zed's own
  MCP-server extension format is being deprecated in favor of the official registry).
- ADDED: no mcp SDK v2 migration inside this project's critical path — 1.28.1 works
  with all current clients (verified configs); schedule separately (§Temporal).

### §9 Open questions — decisions (recommendations confirmed by research)
1. **Private repos: public HTTPS only first.** (Verified supporting fact: git
   requires credentials retry on 401; SSH path adds key-management surface before
   the public path is battle-tested. Shadow-canary precedent.) → Фаза 2.5.
2. **Remote cache: LRU(5) + TTL 24h** — reuse `ProjectIndexerRegistry` number
   (no known issue on it); TTL 24h justified: remote clones should expire
   themselves; Bazel disk-cache GC (size+age+idle) as the eviction mechanism.
3. **Remote write: read-only default, per-workspace opt-in flag, verify_action
   gate.** (Direct continuation of owner's own "Verify is 80% of the work"
   position to Mikatoshi.)

### Language section — Python stays; evidence
- Core (DI, tools, IntelligenceLayer, Indexer/Searcher/SymbolIndex): Python, tested,
  don't rewrite (verified this session: 47 tool classes + 1398 tests).
- Tree-sitter, LanceDB, BM25, embeddings: Python-first ecosystems, no parity in
  other languages (WISDOM-verified).
- Streamable HTTP transport: the official Python SDK provides it (verified in venv).
- `GitUrlSource` I/O bottleneck: only IF profiling (py-spy) shows GIL is the limit;
  not preemptively (ТЗ's own rule; §1.20 proportionality).

### §10 Reranker and heavy layers — defaults (from our own numbers, WISDOM)
| Layer | Decision | Cost (documented) |
|---|---|---|
| BM25/FTS5 + SymbolIndex/Call Graph | **ON always** (recall carrier, fts5_only 0.825 > full 0.775) | cheap, no external calls |
| Reranker | flag `--reranker` (precision +0.147, recall −0.019) | ~1200ms vs 300ms |
| Vector (e5-small) | flag `--vector-search`, hybrid complement only (recall 0.083-0.167 — weakest for symbols) | embed runtime |
| CoT/reasoning | flag `--cot`, pointwise (recall gain ×30-65 token cost; glm loses 16-26% on EMPTY_CONTENT) | tokens ×30-65 |
| Late enrichment | OFF (KI-106: 0.0% coverage on search chunks) | — |
New heavy layer rule: evidence-ladder rung + blind control before default (§6.4/12.2).

### §11 Action Receipt — build on ChangeIntent + in-toto envelope (no crypto)

Verified current state: `ExecutionContract` (verify_file_write/git_commit/git_push/
index_sync) + `ChangeIntent{before_hash, after_hash, base_commit, timestamp}` +
`ChangeIntentLedger` (JSONL in data_root) — the receipt skeleton already exists.
Research (fetched): in-toto link = the original "action receipt" (materials/products
= before/after hashes; `MODIFY` = before ≠ after; `expected_command` mismatch is
only a WARNING — commands are forgeable via PATH, don't treat exact-match as
failure); SLSA Provenance (externalParameters vs internalParameters split;
guidance: prefer named verification procedures over inline command lists — a
parameterized command list is impractical to verify because it changes every run);
SLSA L1 permits unsigned provenance; VSA records verification RESULTS (binary);
OpenWorkProof (dengyier, 2026-07) — closest protocol (WorkOrder→ActionReceipt→
AcceptanceReceipt, offline deterministic replay verifier, tri-state
VERIFIED/REFUTED/UNKNOWN with machine reason codes, "UNKNOWN is a safe conclusion,
not a crash", scope-bound verification) — brand-new, 4 stars, treat as precedent,
not battle-tested. SWE-bench: verification-by-rerun works at scale when env is
pinned and test selection frozen. CloudWatch/K8s/Tekton all reserve a third state
for "couldn't verify" (INSUFFICIENT_DATA / Unknown).

Design:
1. **Envelope:** in-toto Statement v1 (`_type`, `subject: [{name, digest}]` with the
   workspace tree digest, `predicateType: "https://mscodebase.dev/action-receipt/v1"`).
2. **Predicate layers:** claim (action_type, agent's claim, per-file before/after
   hashes from ChangeIntent, base_commit) | verification (named procedures — pytest
   marker/script path as `buildType`-style URI + repo digest covers the procedure;
   recorded argv as advisory) | verdict (pure function of re-executed checks).
3. **Tri-state + reason codes:** VERIFIED (steps re-ran, outcome matches claim) /
   REFUTED (a check ran and produced a determinate negative) / INCONCLUSIVE
   (everything else: timeout, env missing, baseline absent) — with machine `reason`
   (`TEST_FAILED`, `HASH_MISMATCH`, `BASELINE_MISSING`, `CHECK_TIMEOUT`, …) + human
   `message` (K8s condition pattern). Scope pinning: exact test selection + revision
   attached to every "tests passed" claim; a receipt says "these N tests passed on
   tree X", never "the fix works".
4. **Steps (§11.5):** (1) extend `verify_action` with receipt fields — mostly
   reusing ChangeIntent; (2) new `get_action_receipt(action_id)` — store receipts in
   the SAME store as project memory (intel_add_memory_node, section="receipts" per
   ТЗ) — BUT note: memory store is for small JSON nodes; receipts carry evidence
   refs (hash + path), evidence blobs live in data_root, memory holds the envelope;
   (3) reproducibility test: for each verification_steps type, generate
   `reproducible_by`, execute in clean env, assert verdict matches (E-05 on 10-20
   real actions); (4) retention: INCONCLUSIVE expires fast, VERIFIED/REFUTED while
   referenced, evidence GC by max-age/size (Bazel disk-cache precedent); receipts
   immutable — a re-verification that flips a verdict = NEW receipt superseding the
   old (never mutate).
5. **Env fingerprint = advisory only** (SLSA internalParameters role): mismatch →
   INCONCLUSIVE + warning, never REFUTED ("environment differs" doesn't falsify).
6. **E-05 is the gate before §11 becomes default** (ТЗ §12.3 explicitly flags §11 as
   extrapolation): the suspicion is `reproducible_by` may not reproduce 1:1 (flaky
   tests, env drift — Bazel documented failure modes). If it fails on real actions,
   §11 degrades to "informative log", not verification.

### §12 Research-driven build process
Adopt the 4-step protocol for every new subsystem (hypothesis with number → minimal
experiment → verdict recorded, incl. "do not repeat" → blind control before default).
Mark in this plan which items are owner-verified vs extrapolation (ТЗ §12.3
accepted). Quarterly re-test of one prior conclusion (E4/E4b precedent). This plan
document itself follows the format: each design decision above cites an experiment
or a fetched source.

---

## 2. Experiment log (this session)

### E-01 — RED TEAM: external plugin load = RCE (run 2026-08-18)
Command: temp plugin `.py` written to `%TEMP%`, loaded via
`importlib.util.spec_from_file_location` + `exec_module`.
Raw output (venv python):
```
=== ATTACK: naive external plugin load (ТЗ 5.2) ===
plugin: C:\Users\...\Temp\plugin_attack_cm6wzpng\evil_plugin.py
sha256[:12]: 74d6c0dc7b14
marker exists after import: True
marker content: plugin executed with pid: 6888
>>> RCE CONFIRMED: code ran inside the loading process on startup
=== MITIGATION: trust gate (hash-pin per plugin+version) ===
BLOCKED before import — prompt user (name/version/sha256/source)
=== DRIFT: plugin modified after trust -> hash changed -> re-prompt ===
old: 74d6c0dc7b14 new: 430431f87a55 re-prompt needed: True
```
Verdict: **attack confirmed; mitigation (hash-pin + trust gate) confirmed; drift
detection confirmed.** Side-finding: our `validate_code` AST gate already blocks
`importlib.util.module_from_spec` — useful precedent for plugin-gate design, but the
MCP process must not depend on it.

### E-02 — GitUrlSource feasibility (run 2026-08-18)
| Probe | Result |
|---|---|
| `git clone --depth 1` Hello-World | 1.2s, 80KB |
| `git clone --depth 1 --filter=blob:none` psf/requests | 2.9s, 7.7MB, 130 files in tree; full clone = 19MB (~60% saved) |
| Fingerprint: `git rev-parse HEAD` + `git ls-tree -r HEAD` | 79ms, zero content re-hash |
| Nonexistent URL | exit 128, clean fatal → INCONCLUSIVE mapping |
| `file://` scheme | exit 128 (git ≥2.38 blocks by default) — but we reject at parse time, not rely on this |

Also measured/noted: piping through `tail` masks git's exit code (`$?` = 0) — the
subprocess contract must use `Popen` + `communicate` (WISDOM §5.16), never
`capture_output` in daemon threads, never trust `$?` through a pipe.

### Queued experiments (per phase, from research gaps)
- E-03: clone→index full pipeline on 5-10 public repos (Фаза 2 DoD; incl. big-repo
  limits probe).
- E-04: blind control for evidence formats in remote/plugin context (rung-style).
- E-05: Action Receipt `reproducible_by` on 10-20 REAL actions (Фаза §11 gate;
  the ТЗ's own §12.3 suspicion).
- E-06: plugin isolation comparison — subprocess/JSON-RPC vs in-process vs
  RestrictedPython vs wasmtime (overhead, breakage).
- E-07: transport equivalence stdio vs HTTP (same request → same JSON); E-07b:
  stateless mode impact on notifications/background tasks.
- E-08: SSRF suite — redirect-to-private-IP, DNS-rebinding probe, file:// rejection,
  localhost/metadata blocking, against our own test host only.
- E-09: upload decompression bomb + path-traversal extraction tests.
- E-10: multi-client HTTP concurrency — 2 clients, 1 workspace: correctness of
  results (not just "no exceptions", §5.13 rule) + write-exclusion lock.

---

## 3. Attack register (mapped to phases)

| # | Vector | Phase | Defense | Status |
|---|---|---|---|---|
| R-1 | Layer bleed (tool imports platform/zed code after refactor) | 0 | CI grep gate on `src/mcp/tools/` + `src/sources/` | planned |
| R-2 | SSRF via git URL (redirect/rebinding/IMDS) | 2 | scheme+domain allowlist, all-A/AAAA check, redirect re-validation, protocol.file.allow=never | planned (E-08) |
| R-3 | Upload bombs / path traversal | 2 | size caps, extraction guard, TTL GC | planned (E-09) |
| R-4 | Plugin RCE | 4 | trust gate + hash-pin + subprocess isolation + self-check registration | **demonstrated (E-01)** |
| R-5 | Remote auth bypass / rate-limit abuse | 3 | Bearer token, SlidingWindowRateLimiter + CircuitBreaker per token/IP, /healthz | planned |
| R-6 | Secrets leak in GitUrlSource (token in URL/cache) | 2.5 | tokens only in `.env`/keychain, never in cache path, URL userinfo rejected | planned |
| R-7 | License pollution (GPL code in agent suggestions) | 2 | documented limitation in README/KNOWN_ISSUES (ТЗ §9б-3) | planned |
| R-8 | Multi-client write race on shared workspace | 3 | workspace-level lock (PID-lock pattern generalized), read-shared/write-exclusive | planned (E-10) |

---

## 4. Interaction matrix (see D-3) — risks owned by layer

| Concern | Layer | Solution |
|---|---|---|
| Zed-specific multi-window (2 processes) | adapter/zed | existing PID-lock + port-ready + CWD-first resolve (keep) |
| Multi-project across editors | core | ProjectIndexerRegistry LRU(5) promoted to core |
| HTTP multi-client shared read | core | index cache reuse; read-only until opt-in |
| HTTP multi-client concurrent write | core | workspace lock; verify_action gate; INCONCLUSIVE on contention |
| notify_change dedup across processes | core | per-client DebounceBatch; DatabaseLock serializes LanceDB writes; E-10 verifies content correctness |
| Windows/Linux/macOS parity | adapters | Фаза 0 extraction; CI ≥2 OS from first PR |
| Plugin trust across machines | plugins | per-machine trust record (hash-pin), NOT synced |

---

## 5. Temporal

- **T+0:** phases 0-1 in-place, safe. mcp==1.28.1 fine for all current clients.
- **T+30d:** Python 3.10 EOL 2026-10 → CI matrix must drop it (pin 3.11/3.12/3.14);
  mcp SDK v2 migration must be scheduled (1.28.1 = 2025-era wire; spec moved to
  2026-07-28 — clients still negotiate today, but v1.x is maintenance-only);
  official MCP registry schema must be checked before designing distribution
  (docs page 404s today — check llms.txt index + registry API).
- **T+180d:** if remote mode goes multi-tenant, the current "one engine, many
  clients" boundary must be re-negotiated (auth, isolation); plugin API drift —
  mitigated by `requires_engine_version` + `schema_version` + quarterly blind
  re-tests (§12).

---

## 6. Next action (recommended start)

1. Open branch `feat/universal-engine`.
2. Фаза 0 first PR: extract `adapters/local_fs/windows.py` + `adapters/zed/` with
   grep-gates; run 1398 tests + smoke_e2e on Windows; add Linux job to CI matrix in
   the SAME PR (§9б-8).
   → **DONE locally 2026-08-18** (moves + `scripts/check_layer_boundaries.py` +
   1300 tests green; uncommitted). Remaining Фаза 0 items: CI matrix ≥2 OS;
   smoke_e2e re-run; commit/PR by owner.
3. Meanwhile, E-03 (clone→index on 5-10 repos) and E-05 (receipt reproducibility)
   can run in `experiments/universal-engine/` without blocking Фаза 0.

RU translation of this plan available on request.
