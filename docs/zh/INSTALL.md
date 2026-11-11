# 安装 MSCodebase Intelligence

> 翻译：2026-11-12，来源 docs/en/INSTALL.md。英文版为准。

<p align="center">
  <img src="../../logo/baner.png" alt="MSCodeBase Banner" width="100%"/>
</p>

[🇬🇧 English](../en/INSTALL.md) • [🇷🇺 Русский](../ru/INSTALL.md) • [🇨🇳 中文](INSTALL.md)

> 2026-11-12 依据 `install.py` v3.2 重写。服务器是本地 MCP 服务器，安装器
> **与宿主无关**：它只创建普通 Python 环境，任何 MCP 宿主都能启动。Zed 是可选
> 适配器。默认安装是 **text-first**：不使用嵌入、GPU、网络，除非明确要求，否则
> 不下载任何模型。

---

## 1. 要求

| 组件 | 要求 |
|---|---|
| 操作系统 | Windows 10+（验证平台）、Linux（CI）、macOS |
| Python | **3.14+**（仅测试 3.14） |
| 内存 | 4 GB；启用本地模型时 8 GB+ |
| 磁盘 | 无模型约 1.5 GB（主要是 venv）；`--with-models` 再加约 650 MB |
| 宿主 | OpenCode、Zed、Claude Code、Cursor 或任意 MCP 客户端 |
| 可选 | LM Studio / Ollama / llama.cpp（重排与 legacy dense 路径） |

开发机不需要 Docker/WSL。容器构建是部署选项（`deploy/docker/`）。

## 2. 安装

```bash
cd <repo-root>
python install.py                     # venv + 依赖 + 代码；text-first
python install.py --with-models       # 同上 + ONNX/GGUF 模型（约 657 MB，需网络）
python install.py --no-zed            # 完全不修改 Zed 设置
python install.py --yes               # 非交互：接受每个步骤
```

Windows 另有 `install.bat`；Linux/macOS 有 `install.sh`。安装器会：

1. 结束旧的 MCP/llama 进程，确保运行的是新代码；
2. 创建/更新虚拟环境并安装锁定依赖；
3. 复制代码到安装根（`--sync-only` 跳过 1–2，只做这一步）；
4. 可选（Zed 适配器）向 `settings.json` 写入 `context_servers` 条目；
5. 在安装根写入 `uninstall.bat` / `uninstall.sh`。

默认安装根（名字是历史遗留，内容与 Zed 无关）：

```
Windows : %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence
macOS   : ~/Library/Application Support/Zed/extensions/mscodebase-intelligence
Linux   : ~/.local/share/zed/extensions/mscodebase-intelligence
```

用 `MSCODEBASE_INSTALL_ROOT=<path>` 可移动；缓存/日志/产物在
`MSCODEBASE_DATA_DIR`（默认 `%LOCALAPPDATA%\mscodebase`）。各路径与实测大小：
[DATA_MAP.md](DATA_MAP.md)。

不用安装器（任何提供 console scripts 的管理器，入口点
`mscodebase-mcp = src.main:main`）：

```bash
pipx install .      # 或：uv tool install .
```

## 3. 更新循环（最容易出错的环节）

安装副本不在仓库里：

```bash
python install.py --sync-only    # 复制代码、清 __pycache__，不装 pip/模型
# 然后重启宿主：OpenCode 会话、Zed 窗口或 CLI 进程
```

`--sync-only`（别名 `--sync`）是改代码后的快速路径。不重启则旧进程继续运行；不
sync 则安装位置仍是旧代码。两者都必需。

## 4. 连接宿主

不要手写命令 —— 打印出来再粘贴到宿主配置：

```bash
python install.py --print-config --client generic      # mcpServers 风格宿主
python install.py --print-config --client opencode
python install.py --print-config --client zed
python install.py --print-config --client claude-code
python install.py --print-config --client cursor
```

各客户端的文件名、可复制 JSON 与启动校验
（`python scripts/verify_client_snippets.py`）见 [CLIENTS.md](CLIENTS.md)。

## 5. 验证

在助手面板中依次执行：

```
tool_help()                                   # 配置档 + 可见/隐藏工具
get_health_report()                           # 索引、提供方、资源
codebase(action="index", path="status")       # chunks > 0?
```

若文本索引缺失或过期：

```bash
python scripts/reindex_text_only.py --project .   # 分块 + 图，不用嵌入
python scripts/rebuild_graph.py                   # 仅图
```

然后重启服务器，让新进程打开重建后的存储。本仓库的实测数字见
[FACTS.md](../FACTS.md)。

## 6. 磁盘上有什么，以及如何清除

```bash
python install.py --doctor            # 版本、路径、大小、索引状态（--json）
python install.py --clean --dry-run   # 列出每个产物及大小；不删除
python install.py --clean             # 询问确认后删除
python install.py --clean --yes       # 不询问（脚本）
```

`--clean` 删除安装根（代码 + venv + 模型 + 卸载器）、数据根
（`projects/`、`logs/`、`models/`、`repos/`）以及当前项目的 `.mscodebase`、
`.codebase_indices`、`.codebase`、`.codebase_models`。它拒绝删除源代码检出、文件
系统根或用户主目录，并在有残留（被运行中的宿主锁定）时以非零码退出。缓存策略
（日志轮转、7/30/90 天清理、克隆 LRU(5)+24 小时）见 [DATA_MAP.md](DATA_MAP.md)。

## 7. 卸载

```bash
python install.py --clean --yes       # 所有层，已验证：剩余 0 字节
./uninstall.bat                       # Windows：由 step_uninst 生成
```

生成的卸载器只结束服务器进程并删除安装根；`--clean` 是完整版本。两者都不修改
宿主配置：请自行从 `settings.json`（Zed）、`opencode.json`（OpenCode）或
`.mcp.json` / `.cursor/mcp.json` 删除 `mscodebase` 条目。

## 8. 可选提供方

| 提供方 | 用途 | 位置 |
|---|---|---|
| llama.cpp (GGUF) | 按需重排、legacy dense 路径 | `LLAMA_CPP_PORT`（8080）、重排 8081 |
| LM Studio | HTTP 嵌入/重排 | `LM_STUDIO_HOST:1234` |
| Ollama | HTTP 嵌入/重排 | `OLLAMA_HOST:11434` |
| basedpyright | 六个 `lsp_*` 工具 | PATH 或扩展 venv |

默认 text-first 回答不需要它们中的任何一个。提供方配置：
[CONFIGURATION.md](CONFIGURATION.md)。

## 9. 故障排查

| 症状 | 可能原因 |
|---|---|
| 缺少期望的工具 | `core` 档案 —— 运行 `tool_help()`，切换到 `full` |
| 任何查询都"未找到" | 索引为空 —— 检查 `codebase(action="index", path="status")` |
| 新代码没有效果 | 未执行 `--sync-only` 和/或未重启宿主 |
| 服务器启动但工具超时 | 提供方或 LSP 挂起 —— 见 [GRACEFUL_DEGRADATION.md](GRACEFUL_DEGRADATION.md) |
| Windows 弹出控制台窗口 | 子进程缺少 `CREATE_NO_WINDOW` —— 见 [ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md) |
| `--clean` 留下文件 | 被运行中的宿主锁定 —— 停止宿主后重试 |
