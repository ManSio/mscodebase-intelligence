# 客户端与部署

> 翻译：2026-11-12，来源 docs/en/CLIENTS.md。英文版为准。

> 2026-11-12 重写。描述各宿主如何启动服务器，以及 `install.py` 究竟安装了什么。
> 已对照 `install.py`、`adapters/clients/snippets.py`、`src/main.py`、`extension.toml`、
> `.opencode/plugin/`、`tests/test_install_cli.py` 与 `scripts/verify_client_snippets.py`
> （后者会从每个片段真正启动服务器）核实。

## 1. 服务器是什么

一个使用 stdio 通信的 Python MCP 服务器（`src/main.py`，入口点
`mscodebase-mcp = src.main:main`，见 `pyproject.toml`），外加一个可选的
Streamable-HTTP 入口（`src/remote_main.py`），用于 docker/远程部署。它本身不是
编辑器插件 —— 由宿主启动它并通过 MCP 通信。

自 v3.2 起安装器**与宿主无关**：它只在磁盘上放置一个普通 Python 环境，任何 MCP
客户端都能启动它。Zed 只是其中一个适配器，不是必需步骤。

## 2. 安装一次服务器

```bash
cd <repo-root>
python install.py                     # venv + 依赖 + 代码（模型步骤会询问）
python install.py --no-zed            # 完全不修改 Zed 设置
python install.py --sync-only         # 改代码后：仅复制代码
```

默认安装位置（历史路径，仅名字与 Zed 有关）：

```
Windows : %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence
macOS   : ~/Library/Application Support/Zed/extensions/mscodebase-intelligence
Linux   : ~/.local/share/zed/extensions/mscodebase-intelligence
```

用 `MSCODEBASE_INSTALL_ROOT=<path>` 可放到任意位置。缓存、日志与项目产物在别处
（`MSCODEBASE_DATA_DIR`，默认 `%LOCALAPPDATA%\mscodebase`）。完整清单见
[DATA_MAP.md](DATA_MAP.md)。

不用安装器的替代方式（任何提供 console scripts 的包管理器）：

```bash
pipx install .        # 或：uv tool install .
mscodebase-mcp        # 入口点已在 PATH 中
```

## 3. 为你的宿主生成配置

不要手写命令与环境变量 —— 让安装器打印：

```bash
python install.py --print-config --client generic      # 任何 mcpServers 风格宿主
python install.py --print-config --client opencode
python install.py --print-config --client zed
python install.py --print-config --client claude-code
python install.py --print-config --client cursor
```

每条命令只打印一个 JSON 对象，因此可以重定向：
`python install.py --print-config --client cursor > .cursor/mcp.json`。片段中已包含
解析后的解释器、`-u -m src.main`、`PYTHONPATH`、`PROJECT_PATH` 和 `PYTHONUTF8=1`。

### 3.1 通用 MCP 客户端（`mcpServers`）

文件：宿主读取其 MCP 配置的位置。`<project>` 是要索引的工作区（即 `PROJECT_PATH`）。

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

文件：项目根目录或 `~/.config/opencode/` 下的 `opencode.json(c)`。OpenCode V2 把
服务器名称放在 **`mcp.servers`** 之下 —— 扁平的 V1 形式 `mcp.<name>` 仍被接受
（迁移兼容），但不是新配置的写法（来源：<https://opencode.ai/docs/mcp-servers>，
"V2 does not place server names directly under `mcp`"）：

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

也可以让 CLI 写入（会保留其它设置）：

```bash
opencode mcp add mscodebase -- <install-root>/venv/Scripts/mscodebase-mcp.exe -u -m src.main
```

若宿主会展开工作区变量，`PROJECT_PATH` 可替换为该变量。配置修改无需重启即生效
（`/reload` 可强制重载）。项目级自动化在 `.opencode/plugin/mscodebase_gate.ts` 与
`.opencode/command/*.md`（见 [HOOKS_AND_GATES.md](HOOKS_AND_GATES.md)）。

### 3.3 Zed（支持，但不是主要宿主）

可以让安装器修改 `settings.json`（默认步骤，用 `--no-zed` 关闭），或把打印出的片段
粘贴到 `context_servers` 下：

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

键与 `adapters/zed/zed_config.py::_make_server_entry` 写入的一致。Windows/Zed 细节：
[ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md)。

### 3.4 Claude Code

项目根目录的 `.mcp.json`，与 3.1 相同的 `mcpServers` 结构。等价的 CLI 写法：

```bash
claude mcp add-json mscodebase '{"command":"<install-root>/venv/Scripts/mscodebase-mcp.exe","args":["-u","-m","src.main"],"env":{"PYTHONPATH":"<install-root>","PROJECT_PATH":"<project>","PYTHONUTF8":"1"}}'
```

### 3.5 Cursor

文件：`.cursor/mcp.json`（或 `~/.cursor/mcp.json` 用于所有项目），结构与 3.1 相同：

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

## 4. 不用 GUI 验证片段

```bash
python scripts/verify_client_snippets.py --install-root <install-root>
```

脚本按安装器的相同方式渲染每个客户端的片段，在临时目录中启动该命令，完成 MCP
`initialize` + `tools/list` 握手，并为每个客户端打印一行。预期结果（2026-11-12 实测）：

```
generic      PASS: server=MSCodebase Intelligence Server tools=17
opencode     PASS: server=MSCodebase Intelligence Server tools=17
zed          PASS: server=MSCodebase Intelligence Server tools=17
claude-code  PASS: server=MSCodebase Intelligence Server tools=17
cursor       PASS: server=MSCodebase Intelligence Server tools=17
```

`tools=17` 是默认 `core` 档案（注册 69，可见 17）；档案表见 README。

在代理面板中依次执行：

```
tool_help()                                   # 档案 + 可见/隐藏工具
get_health_report()                           # 索引、提供方、资源
codebase(action="index", path="status")       # chunks > 0?
```

## 5. 更新循环

安装副本不是 git 检出：

```
修改 src/... -> python install.py --sync-only -> 重启宿主（会话 / 窗口）
```

不重启则旧进程继续提供旧代码；不 sync 则安装位置没有新代码。两步都必需。如果直接
从检出运行 —— 把检出路径写进 `command`/`PYTHONPATH`，就不需要 sync。

## 6. 远程 / Docker

`src/remote_main.py` 提供带 bearer 令牌的 Streamable HTTP；
`deploy/docker/Dockerfile` + `docker-compose.yml` 构建镜像，CI 运行 `docker-build`
job。Docker 是部署选项，不是本地必需。

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

## 7. 脚本与 CI（完全不用 MCP）

```bash
python -m src.cli <tool> '<json-args>' [--project <root>]
echo '<json>' | python -m src.cli <tool> -
```

CLI 使用同一 DI 容器与同一批工具类；分发器是精选的 allowlist（`src/cli.py`），
而不是全部 69 个工具。

## 8. 缺陷报告应包含什么

说明宿主（OpenCode / Zed / Claude Code / Cursor / generic / CLI）、档案
（`core`/`full`）以及服务器的启动方式。缺少这三项的报告无法区分
"工具被档案隐藏" 与 "工具损坏"。
