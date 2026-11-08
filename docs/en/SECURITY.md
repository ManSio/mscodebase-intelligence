# Security Policy — MSCodeBase Intelligence

[English](SECURITY.md) · [Русский](../ru/SECURITY.md) · [中文](../zh/SECURITY.md)

> Version 3.5.0 · MIT · local MCP server, no hosted backend

---

## 1. Supported versions

| Version | Supported |
|---|---|
| 3.5.x | yes — current line (`pyproject.toml`) |
| < 3.5 | no; upgrade first, then report |

Only the latest 3.5.x is patched. This is a policy statement, not something the
code enforces. Runtime floor is Python 3.14 (`requires-python = ">=3.14"`); a
report against an older interpreter is out of scope.

## 2. Threat model

The server runs as a **stdio MCP process with the rights of the user who
launched it** — normally the host's user, with no privilege separation, no
container, no seccomp, no network listener by default. That single sentence
drives everything below:

- It can read any file the user can read, and write any file the user can write.
  There is no sandbox around the server itself.
- It indexes and reads **untrusted content**. A repository's `AGENTS.md`,
  `SKILL.md`, source comments, or a fetched page are *data*. They are never
  authority. `src/core/trust_boundary.py` classifies roots as `TRUSTED`,
  `UNTRUSTED` or `UNKNOWN`; `MSCODEBASE_TRUSTED_ROOTS` (separated by `;` or `,`)
  is the explicit allowlist. Instructions from an `UNTRUSTED` root are not
  executed, and running scripts / pushing / installing from one requires the
  owner's explicit confirmation (`docs/TRUST_BOUNDARY.md`).
- The realistic attack is **prompt injection through indexed content**, not a
  remote exploit. The defences are bounded tools, preview-before-write, and one
  dangerous capability that is off by default.

## 3. `execute_script` — the RCE surface

`execute_script` is **disabled by default**. It is registered only when
`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`, and then it is the 70th tool, counted
separately from the 69.

What the code actually does (read this before enabling it):

- `src/core/sandbox/executor.py` validates the source **before** execution:
  a stdlib module allowlist (`ALLOWED_MODULES`), blocked string patterns
  (`os.system`, `subprocess`, `open(`, `eval(`, `__import__`, `sys.modules`,
  `win32`, ...), and AST-level blocks for obfuscated imports.
- Execution is a subprocess with a minimal environment: `PATH=""`, no copy of
  `os.environ` (so parent secrets never reach the child), `PYTHONPATH` set to the
  project root, 30 s default timeout, 1 MB stdout/stderr cap.
- Three modes exist: `strict` (default), `permissive`, `off`.

The module docstring is explicit: **"NOT a security boundary for untrusted
code. Defense-in-depth for agent tools."** Treat enabling it as granting
arbitrary code execution under your account. Note that
`.env.example` and the start-up log message describe it as running "without
sandbox isolation"; the executor above is what the tool actually calls, and the
honest summary is "AST-validated subprocess, not a jail".

## 4. Writes: preview, impact guard, receipt

- `WriteTool.execute` defaults to `apply=False`: every rename/move/replace/
  insert/delete returns a **preview**. Nothing is written until `apply=True`.
- The same method is decorated with
  `@modification_guard(pagerank_min=0.05, blast_min=10, ack_ttl=600)`. For a
  load-bearing file (high PageRank, or blast radius >= 10 connections) the guard
  **denies** the write and returns an HMAC `impact_token` bound to the file's
  current `mtime:size`.
- `ack_impact(file_path, impact_token)` opens a 600 s window. The token is
  invalidated if the file changes, so a stale acknowledgement cannot authorise a
  write against different content. A bare ack without a token is rejected.
- Ambiguity is refused, not resolved: a bare symbol matching more than one
  definition returns `denied` with the candidate list instead of silently
  picking the first.
- Fail-closed: if PageRank or blast-radius lookup fails, the guard assumes the
  file is hot (PageRank 1.0 / blast 100) and demands an ack.
- Every write is recorded through `ActionReceipt`; `get_action_receipt` (full
  profile) returns what was changed.

## 5. Paths, reads, and the index

- `SecurityConfig` parses `MAX_FILE_SIZE_MB` (10), `ALLOWED_EXTENSIONS`,
  `ALLOW_SYMLINKS` (`true`) and `STRICT_PATH_VALIDATION` (`true`) from the
  environment, but **no other module reads those four values today**. The real
  file filtering lives in `src/core/indexing/file_guard.py` (size cap constant,
  extension allowlist, minified/binary detection, `.gitignore` patterns) and the
  real path containment is the explicit `is_relative_to` checks below. Do not
  treat the env flags as active security controls.
- Path containment is enforced where it matters, via `Path.resolve()` +
  `is_relative_to`: `read_live_file` when `MSCODEBASE_RESTRICTED_READ=true`
  (default off — an absolute path outside the project is readable), `grep_code`
  (must stay inside the project root), the upload destination, and
  `autonomous_fix`.
- Self-indexing is refused: `resolve_indexer_for_request()` rejects the extension
  directory and the MCP install path instead of quietly indexing its own code.
- The indexer skips `.git`, system dirs, binaries, minified files, oversized
  files, `.gitignore`d paths and `experiments/**` (`file_guard.py`).
- The server does not open a TCP port unless you configure a transport
  (`MCP_HOST`/`MCP_PORT`, default `127.0.0.1:8765` for the SSE bridge). Nothing
  is exposed to the network by default; llama.cpp/ONNX/LM Studio endpoints are
  loopback too.

## 6. Secrets

- Secrets live in `.env` only. `.env`, `.env.local`, `.mscodebase/`,
  `.codebase_models/` and `models/` are git-ignored.
- The LM Studio default key `sk-local` in `.env.example` is a documented
  placeholder, not a credential.
- Never paste a key into a tool argument, a doc, a test fixture or a log line.
  `src/core/redact.py` strips `PREFIX`-anchored credential shapes before text is
  injected into an agent's context, and its own docstring says it is **not** a
  security boundary — it only catches known forms.

## 7. This repository is public

MIT-licensed and publicly readable. Therefore:

- No third-party dumps: scraped pages, profile exports, other people's emails,
  whole articles. Our own conclusion plus a `sha256`, the source URL and a short
  quotation is what belongs here.
- A verbatim copy also imports the source's licence (a CC BY-NC-SA article
  would contaminate an MIT repository).
- Gate: `scripts/check_third_party_data.py` runs in pre-commit. R1 (personal
  email) and R2 (scraped-profile signature) block; R3 (bulk verbatim third-party
  text) is advisory; R4 catches thread dumps.
- Raw material that must be kept lives **outside** the repository, under
  `<data_root>/audit-cache/<task>/`.

## 8. Reporting a vulnerability

1. Open a private advisory:
   https://github.com/ManSio/mscodebase-intelligence/security/advisories/new
2. Prefix the subject with `[SECURITY]` and include: affected version, host
   (OpenCode / Zed), the tool involved, a minimal reproduction, and whether
   `execute_script` was enabled.
3. Do not open a public issue first, and do not include secrets or third-party
   personal data in the report.

Expect an initial response within a few days. Because this is a single-maintainer
project, a fix may land as a normal patch release rather than a backport.

---

**Verified against:** `pyproject.toml`, `src/mcp/server_tools.py`,
`src/mcp/tools/codebase_tool.py`, `src/mcp/tools/write_tools.py`,
`src/core/sandbox/executor.py`, `src/core/modification_guard.py`,
`src/core/trust_boundary.py`, `src/core/error_handler.py`,
`src/config/settings.py`, `src/mcp/tools/system_tools.py`,
`src/mcp/tools/grep_tool.py`, `src/core/indexing/file_guard.py`,
`src/core/autonomous_fix.py`, `src/sources/upload/__init__.py`, `src/core/change_preview.py`,
`src/core/redact.py`, `scripts/check_third_party_data.py`, `.env.example`,
`.gitignore`, `docs/TRUST_BOUNDARY.md`.
