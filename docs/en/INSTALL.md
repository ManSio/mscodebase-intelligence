# Installing MSCodebase Intelligence

<p align="center">
  <img src="../../logo/baner.png" alt="MSCodeBase Banner" width="100%"/>
</p>

[English](INSTALL.md) · [Русский](../ru/INSTALL.md) · [中文](../zh/INSTALL.md)

> Rewritten 2026-11-12 against `install.py` v3.2. The server is a local MCP server
> and the installer is **host-neutral**: it creates a plain Python environment, and
> any MCP host launches it. Zed is an optional adapter. The default install is
> **text-first** — no embeddings, no GPU, no network and no model download unless you
> ask for them.

---

## 1. Requirements

| Component | Requirement |
|---|---|
| OS | Windows 10+ (validated platform), Linux (CI), macOS |
| Python | **3.14+** (only 3.14 is tested) |
| RAM | 4 GB; 8 GB+ if you enable local models |
| Disk | ~1.5 GB without models (venv dominates); +~650 MB with `--with-models` |
| Host | OpenCode, Zed, Claude Code, Cursor or any MCP client |
| Optional | LM Studio / Ollama / llama.cpp for rerank and the legacy dense path |

Docker and WSL are not required on the development machine. The container build is a
deployment option (`deploy/docker/`).

## 2. Install

```bash
cd <repo-root>
python install.py                     # venv + dependencies + code; text-first
python install.py --with-models       # same + ONNX/GGUF models (~657 MB, network)
python install.py --no-zed            # do not touch Zed settings at all
python install.py --yes               # non-interactive: accept every step
```

Windows also has `install.bat`; Linux/macOS have `install.sh`. The installer:

1. stops stale MCP/llama processes so the new code is really the code that runs;
2. creates/updates the virtual environment and installs the pinned dependencies;
3. copies the code into the install root (`--sync-only` skips 1–2 and does just this);
4. optionally (Zed adapter) writes the `context_servers` entry into `settings.json`;
5. writes `uninstall.bat` / `uninstall.sh` into the install root.

Default install root (the name is historical, nothing Zed-specific about the
contents):

```
Windows : %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence
macOS   : ~/Library/Application Support/Zed/extensions/mscodebase-intelligence
Linux   : ~/.local/share/zed/extensions/mscodebase-intelligence
```

Relocate it with `MSCODEBASE_INSTALL_ROOT=<path>`; caches/logs/artifacts go to
`MSCODEBASE_DATA_DIR` (default `%LOCALAPPDATA%\mscodebase`). What lands where, with
measured sizes: [DATA_MAP.md](DATA_MAP.md).

Without the installer (any manager that exposes console scripts, entry point
`mscodebase-mcp = src.main:main`):

```bash
pipx install .      # or: uv tool install .
```

## 3. Update loop (the part people get wrong)

The installed copy lives outside the repository:

```bash
python install.py --sync-only    # copy code, drop __pycache__, no pip/models
# then restart the host: the OpenCode session, the Zed window, the CLI process
```

`--sync-only` (alias `--sync`) is the fast path after every source change. Skipping
the restart leaves the old process running; skipping the sync leaves old code in the
installed location. Both are required.

## 4. Connect a host

Do not hand-write the command: print it, then paste it into the host config.

```bash
python install.py --print-config --client generic      # mcpServers-style hosts
python install.py --print-config --client opencode
python install.py --print-config --client zed
python install.py --print-config --client claude-code
python install.py --print-config --client cursor
```

Per-client file names, copy-paste JSON and the launch check
(`python scripts/verify_client_snippets.py`) are in [CLIENTS.md](CLIENTS.md).

## 5. Verify

From the agent panel, in this order:

```
tool_help()                                   # profile + visible/hidden tools
get_health_report()                           # index, providers, resources
codebase(action="index", path="status")       # chunks > 0?
```

If the text index is missing or stale:

```bash
python scripts/reindex_text_only.py --project .   # chunks + graph, no embeddings
python scripts/rebuild_graph.py                   # graph only
```

Then restart the server so the new process opens the rebuilt stores. Measured numbers
for this repository are in [FACTS.md](../FACTS.md).

## 6. What is on disk, and how to remove it

```bash
python install.py --doctor            # versions, paths, sizes, index state (--json)
python install.py --clean --dry-run   # every artifact with its size; deletes nothing
python install.py --clean             # asks for confirmation, then deletes
python install.py --clean --yes       # no prompt (scripts)
```

`--clean` removes the install root (code + venv + models + uninstaller), the data
root (`projects/`, `logs/`, `models/`, `repos/`) and the current project's
`.mscodebase`, `.codebase_indices`, `.codebase`, `.codebase_models`. It refuses to
delete a path that is the source checkout, a filesystem root or the home directory,
and it reports any residue (locked files from a running host) with a non-zero exit
code. Cache policies (log rotation, 7/30/90-day pruning, LRU(5)+24 h repo cache) are
documented in [DATA_MAP.md](DATA_MAP.md).

## 7. Uninstall

```bash
python install.py --clean --yes       # all layers, verified: 0 bytes left
./uninstall.bat                       # Windows: generated by install.py step_uninst
```

The generated uninstaller kills the server processes and removes only the install
root. `--clean` is the complete version. Neither touches your host config: delete the
`mscodebase` entry from `settings.json` (Zed), `opencode.json` (OpenCode) or
`.mcp.json` / `.cursor/mcp.json` yourself.

## 8. Optional providers

| Provider | Why | Where |
|---|---|---|
| llama.cpp (GGUF) | on-demand rerank, legacy dense path | `LLAMA_CPP_PORT` (8080), reranker 8081 |
| LM Studio | embeddings/rerank over HTTP | `LM_STUDIO_HOST:1234` |
| Ollama | embeddings/rerank over HTTP | `OLLAMA_HOST:11434` |
| basedpyright | the six `lsp_*` tools | PATH or extension venv |

None of them is needed for the default text-first answer. Provider settings:
[CONFIGURATION.md](CONFIGURATION.md).

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Tool you expect is missing | `core` profile — run `tool_help()`, switch to `full` |
| "Nothing found" for any query | empty index — check `codebase(action="index", path="status")` |
| New code has no effect | no `--sync-only` and/or no host restart |
| Server starts, tools time out | provider or LSP hanging — see [GRACEFUL_DEGRADATION.md](GRACEFUL_DEGRADATION.md) |
| Windows console windows flashing | subprocess without `CREATE_NO_WINDOW` — see [ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md) |
| `--clean` left files behind | a running host holds them (locks) — stop the host and re-run |
