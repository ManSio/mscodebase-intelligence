# Windows Quirks (and the Host Situation)

[English](ZED_WINDOWS_QUIRKS.md) · [Русский](../ru/ZED_WINDOWS_QUIRKS.md) · [中文](../zh/ZED_WINDOWS_QUIRKS.md)

> Version 3.5.0. The filename is kept for link stability. **OpenCode is the
> primary host now; the Zed extension is still supported.** Zed-only incidents
> are marked as history at the end and are not current behaviour.

## 1. Hosts

| Host | Launch line | Status |
|---|---|---|
| OpenCode | `…\Zed\extensions\mscodebase-intelligence\venv\Scripts\mscodebase-mcp.exe -u -m src.main`, `PYTHONPATH` = extension dir | primary |
| Zed extension | `extension.toml` → `venv\Scripts\pythonw.exe -u -m src.main`, `PROJECT_PATH = $ZED_WORKTREE_ROOT`, `PYTHONUTF8=1` | supported |

Both run the code copied into `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`.
Editing `src/` changes nothing until `python install.py --sync-only` plus a host
restart. This is the most common "my fix did not apply" cause.

## 2. No console windows: `CREATE_NO_WINDOW` everywhere

Windows spawns a console for every console-subsystem child. The server starts
many (`git`, `llama-server.exe`, `basedpyright`, idle probes), so the flag is
applied in two layers:

1. **Globally** — `src/core/silent_subprocess.py`, imported first by
   `src/main.py`, patches `subprocess.Popen/run/check_output/check_call` on win32
   to OR in `CREATE_NO_WINDOW` and set `STARTUPINFO(wShowWindow=SW_HIDE)`. Any
   library that shells out is covered without knowing about it.
2. **Locally** — dozens of call sites pass `creationflags=CREATE_NO_WINDOW`
   explicitly (`git_tools`, `commit_memory`, `execution_contract`,
   `resource_monitor`, `verify_on_read`, `graph`, `sandbox/executor`, …). The
   flag is OR-ed, never assigned over an existing set.

Long-lived model servers add `DETACHED_PROCESS | CREATE_NO_WINDOW`
(`llama_runner._popen_with_job`), so they survive the parent and do not flash a
window on each restart. This is not cosmetic: a console flashing every ~30 s (the
idle probe) was a recorded incident, read by users as malware.

## 3. `pythonw.exe` vs `python.exe`, and process names

`pythonw.exe` is the GUI-subsystem interpreter: no console, but stdio still works
over the pipes the host provides. `install.py` therefore uses
`venv\Scripts\pythonw.exe` as `MCP_PYTHON` and creates a one-time NTFS hardlink
`mscodebase-mcp.exe → pythonw.exe` (`process_titles.ensure_mcp_hardlink`), falling
back to plain `pythonw.exe` if linking fails.

The hardlink exists because `pythonw.exe` has no console and cannot set a window
title — Task Manager would show a bare `python.exe`. With it, the process is
identifiable. `apply_mcp_process_title()` builds `mscodebase-mcp:<project>-<hash8>`;
`start_server.bat` runs `python.exe` with `PYTHONUTF8=1` and sets the title from
the batch file. `llama-server` children get `llama-embed.exe` / `llama-rerank.exe`
hardlinks for the same reason.

## 4. `Popen` + `communicate`, never `capture_output`

`capture_output=True` and `check_output()` are forbidden inside the MCP process:
when stdout is already redirected into a pipe (as it is under an MCP host) they
can deadlock the pipe in a worker thread and the call never returns. House
pattern:

```python
proc = subprocess.Popen([...], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace",
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
try:
    out, _ = proc.communicate(timeout=...)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.communicate()   # reap; never leave a zombie
```

`stdin=DEVNULL` stops a child that reads stdin from blocking forever.
`.githooks/pre-commit` uses the same pattern and treats a timeout as a verdict
("gate did not answer"), not as a crash.

## 5. Encoding

- `PYTHONUTF8=1` is set in both host configs (`extension.toml`, the OpenCode MCP
  block), so the interpreter does not fall back to the OEM code page.
- Scripts that print emoji reconfigure stdout
  (`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`); otherwise a
  cp1251/cp866 console raises `UnicodeEncodeError` and a gate fails for the wrong
  reason.
- In PowerShell set it per session before reading logs:
  `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`.
- Never `print()` to stdout from library code — stdout is the JSON-RPC channel.
  Diagnostics go to the logger, which writes to `<data_root>/logs/`.

## 6. Paths

- MCP arguments accept native Windows paths (`C:\work\app\src\main.py`); use
  relative paths from the project root for `notify_change`, absolute for
  `project_root`.
- Internal comparison keys are canonical POSIX (`Path.resolve().as_posix()`),
  lower-cased on `win32` because the filesystem is case-insensitive
  (`modification_guard._normalize_path`).
- Paths beyond `MAX_PATH` go through `to_win_long_path()` (`\\?\` prefix; no-op on
  POSIX).
- Comparing `git worktree list` output with `pathlib` paths without normalising
  separators makes a gate see its own tree as foreign — hence the dedicated
  normaliser in `scripts/check_parallel_sessions.py`.

## 7. Git, locks, and Insider builds

Git can block on the graphical Credential Manager from a windowless process, so
every call uses `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=echo`, `GIT_PAGER=cat`, plus
`CREATE_NO_WINDOW` and a timeout (`git_tools._git_run`, 15 s).

Windows keeps memory-mapped DB files locked while a handle is open.
`intel_reset_index()` therefore closes the handle, releases the PID lock, deletes,
and re-acquires — `rmtree` over a held lock used to leave a half-deleted index. If
deletion still hits `PermissionError`, the manager switches to a fresh DB path, and
`artifact_gc` skips locked files and reports them instead of force-deleting. A
folder that refuses to delete usually means another MCP process still holds it.

On Windows Insider builds the UCRT API-set DLLs (`api-ms-win-crt-*`) are absent and
the upstream `llama-server.exe` fails to load; `_patch_dll_imports` rewrites those
imports to `ucrtbase.dll` before first run. Machine-class workaround, not a
requirement.

## 8. History (context only)

- **LSP server for Zed** — a standalone `mscodebase-lsp` process was removed (Zed
  needs a Rust/WASM adapter for custom language servers). The internal LSP
  *client* (basedpyright) survived; the LSP→MCP bridge was removed 2026-07-20 and
  `lsp_*` tools need no bridge.
- **"MCP does not restart"** — Zed had no auto-restart for context servers, so
  every code change needed a full quit. Under OpenCode the equivalent is
  restarting the session; the rule (the process keeps old modules) is unchanged.
- **Restricted Mode / workspace trust** — a Zed first-open dialog. Not a property
  of this server and not verifiable in code (host behaviour).
- **Project resolution** — the Zed SQLite state is still consulted, no longer
  first: explicit argument → CWD → `PROJECT_PATH` → multi-workspace SQLite → Zed
  `workspaces` DB → `ZED_WORKTREE_ROOT` → extension root
  (`project_resolution.resolve_project_root`). CWD precedes the databases because
  it is the only per-process signal with several windows open; see
  `investigations/ACTIVE_WORKSPACE_RESOLUTION.md`.
- **Console flashing** — fixed by §2; kept here because it explains why the
  global patch exists.

---

**Verified against:** `src/main.py` (silent_subprocess import, console title),
`src/core/silent_subprocess.py`, `src/core/process_titles.py`,
`src/providers/reranker/llama_runner.py` (`_popen_with_job`, DETACHED_PROCESS),
`src/mcp/tools/git_tools.py` (`GIT_TERMINAL_PROMPT`/`GIT_ASKPASS`/`GIT_PAGER`),
`src/core/modification_guard.py` (`_normalize_path`),
`src/sources/local_fs/windows.py` (`to_win_long_path`),
`src/core/sandbox/executor.py` (Popen + communicate), `src/core/artifact_gc.py`,
`src/core/intelligence/tools_reg.py` (`intel_reset_index`), `install.py`
(`MCP_EXE`, `_ensure_mcp_hardlink`), `start_server.bat`, `extension.toml`,
`.githooks/pre-commit`, `src/providers/reranker/llama_install.py`
(`_patch_dll_imports`), `src/core/project_resolution.py`,
`src/core/lsp_client.py`, `src/mcp/tools/lsp_tools.py`.
