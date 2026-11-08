# 客户端与部署

> 翻译：2026-11-08，来源 docs/en/CLIENTS.md。英文版为准。

> 2026-11-08 重写。描述各宿主如何启动服务器，以及 `install.py` 究竟安装了什么。
> 已对照 `install.py`、`extension.toml`、`adapters/clients/*`、`.opencode/plugin/`
> 以及开发机上的实时 OpenCode 配置核实。

## 1. 服务器是什么

一个使用 stdio 通信的 Python MCP 服务器（`src/main.py`），外加一个可选的
Streamable-HTTP 入口（`src/remote_main.py`），用于 docker/远程部署。它本身不是
编辑器插件 —— 由宿主启动它并通过 MCP 通信。

## 2. OpenCode（主要宿主）

OpenCode 把服务器作为本地 MCP 服务器启动。开发机上的条目如下（路径已截短）：

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

两个关键事实：

1. **已安装副本**位于扩展目录，而不是 git checkout。把当前代码放进去的正是
   `install.py`（见 §5）。
2. 该目录因历史原因命名为 `…\Zed\extensions\…`。它就是一个普通 Python 环境；
   OpenCode 使用它的方式与 Zed 扩展完全相同。

项目级配置：`.opencode/plugin/mscodebase_gate.ts`（提交钩子）和
`.opencode/command/*.md`（可复用的 agent 命令）。见
[HOOKS_AND_GATES.md](HOOKS_AND_GATES.md)。

## 3. Zed（受支持，但非主要）

Zed 扩展（`extension.toml`、`__mscodebase_ext__.marker`）从同一目录启动同一个
服务器。Windows/Zed 特有的行为记录在 [ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md)；
请把 Zed 视为替代宿主，而不是参考实现。

## 4. 其他 MCP 客户端

`adapters/clients/` 中包含 stdio 与 Streamable-HTTP 的现成配置形状：

| 文件 | 客户端 | 配置段 |
|---|---|---|
| `claude.code.mcp.json` | Claude Code / Desktop | `mcpServers` |
| `vscode.mcp.json` | VS Code（`.vscode/mcp.json`） | `servers` |

填入 `<path-to-venv>`、`<path-to-repo>`、`<path-to-project>`。HTTP 变体指向
`http://<host>:8089/mcp`，并要求
`Authorization: Bearer <MSCODEBASE_REMOTE_TOKEN>`；远程服务器由
`deploy/docker/` 构建。

脚本和 CI 完全不需要 MCP：

```bash
python -m src.cli <tool> '<json-args>' [--project <root>]
```

CLI 使用同一个 DI 容器和工具类；其分发器是一份精选 allowlist（`src/cli.py`），
而不是全部 69 个工具的接口。

## 5. 安装与更新循环

```bash
python install.py            # interactive full install (venv, pip, llama.cpp, models)
python install.py --sync-only  # code only: copy + drop __pycache__, no pip/models
```

`install.py` 把 `src/`、脚本和支持文件复制到
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`（或平台对应位置），
并保留扩展 venv。代码改动之后：

```
edit → python install.py --sync-only → restart the host (OpenCode session / Zed window)
```

不重启，旧进程会继续提供旧代码；不同步，新代码就不在已安装位置的磁盘上。
两个步骤都必需。

## 6. 远程 / Docker

`src/remote_main.py` 暴露带 bearer token 认证的 Streamable HTTP；
`deploy/docker/Dockerfile` + `docker-compose.yml` 构建镜像，CI 运行
`docker-build` 任务。Docker 是部署选项，不是本地必需。

## 7. bug 报告应说明哪个客户端

说明宿主（OpenCode / Zed / Claude / VS Code / CLI）、profile（`core`/`full`），
以及服务器是如何启动的。缺少这三项的报告无法区分“工具被 profile 隐藏”与
“工具损坏”。
