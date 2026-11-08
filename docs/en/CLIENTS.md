# Clients and deployment

> Rewritten 2026-11-08. Describes how the server is launched by each host and what
> `install.py` actually installs. Verified against `install.py`, `extension.toml`,
> `adapters/clients/*`, `.opencode/plugin/`, and the live OpenCode config on the
> development machine.

## 1. What the server is

A Python MCP server (`src/main.py`) speaking stdio, plus an optional Streamable-HTTP
entry point (`src/remote_main.py`) for the docker/remote deployment. It is not an
editor plugin by itself — a host launches it and talks MCP.

## 2. OpenCode (primary)

OpenCode starts the server as a local MCP server. On the development machine the
entry looks like this (paths shortened):

```jsonc
"mcp": {
  "mscodebase-intelligence": {
    "type": "local",
    "command": [
      "C:\\Users\\<user>\\AppData\\Local\\Zed\\extensions\\mscodebase-intelligence\\venv\\Scripts\\mscodebase-mcp.exe",
      "-u", "-m", "src.main"
    ],
    "environment": {
      "PYTHONPATH": "C:\\Users\\<user>\\AppData\\Local\\Zed\\extensions\\mscodebase-intelligence",
      "PROJECT_PATH": "${workspaceRoot}",
      "PYTHONUTF8": "1"
    }
  }
}
```

Two facts that matter:

1. The **installed copy** lives in the extension directory, not in the git checkout.
   `install.py` is what puts current code there (see §5).
2. The directory is named `…\Zed\extensions\…` for historical reasons. It is a plain
   Python environment; OpenCode uses it the same way the Zed extension does.

Project-local configuration: `.opencode/plugin/mscodebase_gate.ts` (commit hooks) and
`.opencode/command/*.md` (reusable agent commands). See
[HOOKS_AND_GATES.md](HOOKS_AND_GATES.md).

## 3. Zed (supported, not primary)

The Zed extension (`extension.toml`, `__mscodebase_ext__.marker`) launches the same
server from the same directory. Behaviour that is specific to Windows/Zed is
documented in [ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md); treat Zed as an
alternative host, not the reference implementation.

## 4. Other MCP clients

`adapters/clients/` contains ready shapes for stdio and Streamable-HTTP:

| File | Client | Section |
|---|---|---|
| `claude.code.mcp.json` | Claude Code / Desktop | `mcpServers` |
| `vscode.mcp.json` | VS Code (`.vscode/mcp.json`) | `servers` |

Fill in `<path-to-venv>`, `<path-to-repo>`, `<path-to-project>`. The HTTP variant
points at `http://<host>:8089/mcp` and requires
`Authorization: Bearer <MSCODEBASE_REMOTE_TOKEN>`; the remote server is built from
`deploy/docker/`.

For scripts and CI there is no MCP at all:

```bash
python -m src.cli <tool> '<json-args>' [--project <root>]
```

The CLI uses the same DI container and tool classes; its dispatcher is a curated
allowlist (`src/cli.py`), not the whole 69-tool surface.

## 5. Installation and the update loop

```bash
python install.py            # interactive full install (venv, pip, llama.cpp, models)
python install.py --sync-only  # code only: copy + drop __pycache__, no pip/models
```

`install.py` copies `src/`, scripts and support files into
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence` (or the platform equivalent)
and keeps the extension venv. After a code change:

```
edit → python install.py --sync-only → restart the host (OpenCode session / Zed window)
```

Without the restart the old process keeps serving the old code; without the sync the
new code is not on disk in the installed location. Both steps are required.

## 6. Remote / Docker

`src/remote_main.py` exposes Streamable HTTP with bearer-token auth;
`deploy/docker/Dockerfile` + `docker-compose.yml` build the image, and CI runs a
`docker-build` job. Docker is a deployment option, not a local requirement.

## 7. Which client should a bug report mention

State the host (OpenCode / Zed / Claude / VS Code / CLI), the profile
(`core`/`full`), and how the server was launched. A report that omits these three
cannot distinguish "tool hidden by the profile" from "tool broken".
