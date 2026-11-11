# Clients and deployment

> Rewritten 2026-11-12. Describes how the server is launched by each host and what
> `install.py` actually installs. Verified against `install.py`, `adapters/clients/snippets.py`,
> `src/main.py`, `extension.toml`, `.opencode/plugin/`, `tests/test_install_cli.py` and
> `scripts/verify_client_snippets.py` (the last one starts the server from every snippet).

## 1. What the server is

A Python MCP server (`src/main.py`, entry point `mscodebase-mcp = src.main:main` in
`pyproject.toml`) speaking stdio, plus an optional Streamable-HTTP entry point
(`src/remote_main.py`) for docker/remote deployment. It is not an editor plugin by
itself — a host launches it and talks MCP.

Since v3.2 the installer is **host-neutral**: it puts a plain Python environment on
disk and any MCP host can launch it. Zed is one adapter among several, not a required
step.

## 2. Install the server once

```bash
cd <repo-root>
python install.py                     # venv + deps + code (model steps ask first)
python install.py --no-zed            # do not touch Zed settings at all
python install.py --sync-only         # after a code change: copy code only
```

Where it lands (default, historical path — nothing Zed-specific about the contents):

```
Windows : %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence
macOS   : ~/Library/Application Support/Zed/extensions/mscodebase-intelligence
Linux   : ~/.local/share/zed/extensions/mscodebase-intelligence
```

Move it anywhere with `MSCODEBASE_INSTALL_ROOT=<path>`; caches, logs and per-project
artifacts live elsewhere (`MSCODEBASE_DATA_DIR`, default `%LOCALAPPDATA%\mscodebase`).


Alternative without the installer (any Python package manager that exposes console
scripts):

```bash
pipx install .        # or: uv tool install .
mscodebase-mcp        # the entry point is now on PATH
```

## 3. Get the config for your host

Do not hand-write the command and the environment — print them:

```bash
python install.py --print-config --client generic      # any mcpServers-style host
python install.py --print-config --client opencode
python install.py --print-config --client zed
python install.py --print-config --client claude-code
python install.py --print-config --client cursor
```

Each command prints one JSON object and nothing else, so it can be redirected:
`python install.py --print-config --client cursor > .cursor/mcp.json`. The snippet
contains the resolved interpreter, `-u -m src.main`, `PYTHONPATH`, `PROJECT_PATH` and
`PYTHONUTF8=1`.

### 3.1 Generic MCP client (`mcpServers`)

File: wherever the host reads its MCP config. Replace `<project>` with the workspace
you want indexed (this is what `PROJECT_PATH` means).

```json
{
  "mcpServers": {
    "mscodebase": {
      "command": "<install-root>/venv/Scripts/mscodebase-mcp.exe",
      "args": ["-u", "-m", "src.main"],
      "env": {
        "PYTHONPATH": "<install-root>",
        "PROJECT_PATH": "<project>",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

### 3.2 OpenCode

File: `opencode.json(c)` at the project root or in `~/.config/opencode/`. OpenCode V2
places server names under **`mcp.servers`** — the flat V1 layout `mcp.<name>` is still
accepted for migrated configs but is not what new configs use
(source: <https://opencode.ai/docs/mcp-servers>, "V2 does not place server names
directly under `mcp`"):

```json
{
  "mcp": {
    "servers": {
      "mscodebase": {
        "type": "local",
        "command": ["<install-root>/venv/Scripts/mscodebase-mcp.exe", "-u", "-m", "src.main"],
        "environment": {
          "PYTHONPATH": "<install-root>",
          "PROJECT_PATH": "<project>",
          "PYTHONUTF8": "1"
        }
      }
    }
  }
}
```

Or let the CLI write it (preserves unrelated settings):

```bash
opencode mcp add mscodebase -- <install-root>/venv/Scripts/mscodebase-mcp.exe -u -m src.main
```

`PROJECT_PATH` may be replaced by the host's workspace variable where the host
expands it. Config changes reload without a restart (`/reload` forces it). Project
automation lives in `.opencode/plugin/mscodebase_gate.ts` and
`.opencode/command/*.md` (see [HOOKS_AND_GATES.md](HOOKS_AND_GATES.md)).

### 3.3 Zed (supported, not primary)

Either let the installer patch `settings.json` (default step, skip with `--no-zed`),
or paste the printed snippet under `context_servers`:

```json
{
  "context_servers": {
    "mscodebase": {
      "command": "<install-root>/venv/Scripts/mscodebase-mcp.exe",
      "args": ["-u", "-m", "src.main"],
      "env": {
        "PYTHONPATH": "<install-root>",
        "PROJECT_PATH": "$ZED_WORKTREE_ROOT",
        "PYTHONUTF8": "1"
      },
      "enabled": true
    }
  }
}
```

Keys match what `adapters/zed/zed_config.py::_make_server_entry` writes. Windows/Zed
specifics: [ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md).

### 3.4 Claude Code

The file `.mcp.json` in the project root uses the same `mcpServers` shape as 3.1.
The CLI form is equivalent:

```bash
claude mcp add-json mscodebase '{"command":"<install-root>/venv/Scripts/mscodebase-mcp.exe","args":["-u","-m","src.main"],"env":{"PYTHONPATH":"<install-root>","PROJECT_PATH":"<project>","PYTHONUTF8":"1"}}'
```

### 3.5 Cursor

File: `.cursor/mcp.json` (or `~/.cursor/mcp.json` for all projects), same
`mcpServers` shape as 3.1:

```json
{
  "mcpServers": {
    "mscodebase": {
      "command": "<install-root>/venv/Scripts/mscodebase-mcp.exe",
      "args": ["-u", "-m", "src.main"],
      "env": {
        "PYTHONPATH": "<install-root>",
        "PROJECT_PATH": "<project>",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

## 4. Verify a snippet without the GUI

```bash
python scripts/verify_client_snippets.py --install-root <install-root>
```

It renders each client's snippet exactly as the installer does, launches that command
in a throwaway directory, performs an MCP `initialize` + `tools/list` handshake and
prints one line per client. Expected (measured 2026-11-12):

```
generic      PASS: server=MSCodebase Intelligence Server tools=17
opencode     PASS: server=MSCodebase Intelligence Server tools=17
zed          PASS: server=MSCodebase Intelligence Server tools=17
claude-code  PASS: server=MSCodebase Intelligence Server tools=17
cursor       PASS: server=MSCodebase Intelligence Server tools=17
```

`tools=17` is the default `core` profile (69 are registered, 17 visible); see the
profile table in the README.

From the agent panel, in this order:

```
tool_help()                                   # profile + visible/hidden tools
get_health_report()                           # index, providers, resources
codebase(action="index", path="status")       # chunks > 0?
```

## 5. The update loop

The installed copy is not the git checkout:

```
edit src/... -> python install.py --sync-only -> restart the host (session / window)
```

Without the restart the old process keeps serving the old code; without the sync the
new code is not on disk in the installed location. Both steps are required. Serving
from a checkout instead? Point `command`/`PYTHONPATH` at the checkout and skip the
sync step.

## 6. Remote / Docker

`src/remote_main.py` exposes Streamable HTTP with bearer-token auth;
`deploy/docker/Dockerfile` + `docker-compose.yml` build the image, and CI runs a
`docker-build` job. Docker is a deployment option, not a local requirement.

```json
{
  "mcpServers": {
    "mscodebase-remote": {
      "type": "http",
      "url": "http://<host>:8089/mcp",
      "headers": { "Authorization": "Bearer <MSCODEBASE_REMOTE_TOKEN>" }
    }
  }
}
```

## 7. Scripts and CI (no MCP at all)

```bash
python -m src.cli <tool> '<json-args>' [--project <root>]
echo '<json>' | python -m src.cli <tool> -
```

The CLI uses the same DI container and tool classes; its dispatcher is a curated
allowlist (`src/cli.py`), not the whole 69-tool surface.

## 8. Which client should a bug report mention

State the host (OpenCode / Zed / Claude Code / Cursor / generic / CLI), the profile
(`core`/`full`), and how the server was launched. A report that omits these three
cannot distinguish "tool hidden by the profile" from "tool broken".
