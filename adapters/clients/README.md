# MSCodeBase — client configs (Phase 5, plan §4)

Thin config shapes for connecting the engine to external MCP clients. Each file
has a stdio variant (local) and an HTTP variant (remote, Phase 3).

**These are shapes, not the recommended way to get a config.** The generated
snippet knows the real paths of your installation:

```bash
python install.py --print-config --client generic        # mcpServers
python install.py --print-config --client claude-code
python install.py --print-config --client cursor
python install.py --print-config --client opencode
python install.py --print-config --client zed
```

The generator lives in `adapters/clients/snippets.py`; the launch check is
`scripts/verify_client_snippets.py`. Full per-client instructions:
`docs/en/CLIENTS.md`.

## stdin/stdout (local)

- **Claude Code / Desktop** — `claude.code.mcp.json` (key `mcpServers`).
- **VS Code** — `vscode.mcp.json` (`.vscode/mcp.json`, key `servers`).
- **Cursor** — same Claude shape (`mcpServers`), file `.cursor/mcp.json` or
  `.mcp.json` in the project root.

Placeholders to fill:

- `<path-to-venv>/Scripts/python.exe` — the engine's venv interpreter
  (POSIX: `<venv>/bin/python3`);
- `PYTHONPATH=<path-to-repo>` — the tree that contains `src/` (the installed copy
  or the checkout);
- `PROJECT_PATH=<path-to-project>` — the project that gets indexed
  (`cwd` is not required: the server reads `PROJECT_PATH`).

`command = <python> -m src.main` starts the server through `run_server` (stdio).

## HTTP (remote, Phase 3)

HTTP block `mscodebase-remote`:

- `url = http://<host>:8089/mcp` — Streamable HTTP entry (`src/remote_main.py`);
- `headers.Authorization = Bearer <MSCODEBASE_REMOTE_TOKEN>` — required on the network.

Building/running the remote server: see `deploy/docker/README.md` (image + compose)
and `src/remote_main.py`.

## CLI (no MCP, for CI/scripts)

`python -m src.cli <tool> '<json>'` — direct tool-class call through DI, see
`src/cli.py`. Curated allowlist: `get_task_status`, `stale_detector`,
`get_context`, `graph_query`, `find_similar_bugs`.
