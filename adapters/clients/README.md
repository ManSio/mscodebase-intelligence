# MSCodeBase — конфиги клиентов (Фаза 5, план §4)

Тонкие адаптеры-конфиги для подключения движка к внешним MCP-клиентам.
Каждый конфиг имеет stdio-вариант (локальный) и http-вариант (remote, Фаза 3).

## stdin/stdout (локально)

- **Claude Code / Desktop** — `claude.code.mcp.json` (секция `mcpServers`).
- **VS Code** — `vscode.mcp.json` (`.vscode/mcp.json`, секция `servers`).
- **Cursor** — использует тот же Claude-формат (`mcpServers`), файл `.cursor/mcp.json`
  или `.mcp.json` в корне проекта.

Заполнить плейсхолдеры:
- `<path-to-venv>/Scripts/python.exe` — venv-py движка (POSIX: `<venv>/bin/python3`);
- `PYTHONPATH=<path-to-repo>` — путь к дереву исходников (`src/`);
- `cwd=<path-to-project>` — проект, который индексируется.

`command = <python> -m src.main` запускает server через `run_server` (stdio).

## HTTP (remote, Фаза 3)

http-блок `mscodebase-remote`:
- `url = http://<host>:8089/mcp` — Streamable HTTP вход (`src/remote_main.py`);
- `headers.Authorization = Bearer <MSCODEBASE_REMOTE_TOKEN>` — обязателен для сети.

Сборка/запуск remote-сервера: см. `deploy/docker/README.md` (образ + compose) и
`src/remote_main.py`.

## CLI (без MCP, для CI/скриптов)

`python -m src.cli <tool> '<json>'` — прямой вызов tool-класса через DI,
см. `src/cli.py`. Curated allowlist: `get_task_status`, `stale_detector`,
`get_context`, `graph_query`, `find_similar_bugs`.
