# 为 Zed IDE 安装 MSCodebase Intelligence

<p align="center">
  <img src="../../logo/baner.png" alt="MSCodeBase Banner" width="100%"/>
</p>

[🇬🇧 English](../en/INSTALL.md) • [🇷🇺 Русский](../ru/INSTALL.md) • [🇨🇳 中文](INSTALL.md)

> **MSCodebase Intelligence** — 用于 Zed IDE 中语义代码搜索的 MCP 服务器。
> 作为 Zed 扩展运行。开发目录：`D:\Project\MSCodeBase`。

---

## 🔧 系统要求

| 组件 | 要求 |
|-----------|-----------|
| **操作系统** | Windows 10+（主要支持），macOS 12+，Linux |
| **Python** | 3.10+（推荐 3.11+） |
| **内存** | 4 GB（推荐 8+ GB） |
| **磁盘** | 500 MB（含模型 — 最高 2 GB） |
| **Zed IDE** | 最新版本 |
| **LM Studio**（可选） | 用于通过 embedding 进行向量搜索 |
| **llama.cpp**（自动安装） | 通过 GGUF 模型内置的 embedder/reranker |

---

## 📥 快速安装

### 第一步：安装扩展

在项目的**根目录**中（`install.py` 所在位置）打开终端并运行：

```bash
python install.py
```

> **Linux/macOS：** 也可以使用 `./install.sh` 进行引导式安装。
> **Windows：** 也可以使用 `install.bat`（双击或在 cmd 中运行）。

安装程序将：
1. ✅ 检查 Python 和兼容性
2. ✅ 创建虚拟环境并安装依赖
3. ✅ 下载并安装 **llama.cpp** + GGUF 模型（`bge-m3` + `bge-reranker-v2-m3`）
4. ✅ 在 Zed 的 `settings.json` 中配置 MCP 服务器
5. ✅ 将源文件复制到已安装的扩展中
6. ✅ 创建 `uninstall.bat`

> **重要：** 安装程序将当前目录中的文件复制到扩展中。
> 所有源代码更改仅在运行 `python install.py` 后生效。

**可用选项：**

| 标志 | 说明 |
|------|------|
| *(无标志)* | 完整安装：复制文件 + 依赖项 + 模型 |
| `--sync` | **快速同步** — 仅复制更改的文件 |
| `--yes` / `-y` | **CI 模式** — 无提示，首次出错即退出 |
| `--skip-models` | 跳过模型下载 |
| `--verbose` / `-v` | 完整框式 UI |
| `--quiet` / `-q` | 仅显示错误，无进度条 |

```bash
# 快速代码同步（日常开发）
python install.py --sync

# 完整安装，无需确认（CI/CD）
python install.py --yes
```

### 自动安装

从 v2.7.0 开始，`install.py` 将自动：

1. **下载 llama-server.exe** 适配您的平台（Windows/macOS/Linux，x64/ARM64）
2. **下载 GGUF 模型**：用于 embedding 的 `bge-m3-Q4_K_M`（417 MB）和用于重排序的 `bge-reranker-v2-m3-Q4_K_M`（418 MB）
3. **在 MCP 启动时运行 llama-server** — 无需任何外部服务
4. **相比 LM Studio 节省高达 5.3 倍内存**（227 MB vs 1200 MB）

整个过程完全自动化。用户无需任何额外操作。

### 第二步：重启 Zed

**File → Quit**，然后重新打开项目。
简单的 `window: reload` **不足以**使更改生效 — MCP 服务器必须完全重启。

### 第三步：验证

打开 **Agent Panel**（`Ctrl+Shift+P` → `Agent Panel: Toggle`）并运行：

```
get_index_status()
```

您应该看到：

```
📂 <your-project-root>
🟢 **MSCodeBase** — active
📦 **Chunks:** `2985` | **Files:** `170` | **Symbols:** `1357`
🧠 **Embedder:** 🦙 llama.cpp
```

如果项目检测不正确（显示其他项目而不是您的项目）— 关闭
所有 Zed 窗口，只打开所需项目。

---

## 🧠 Windows 特殊说明

在 Windows 上，有一些**关键的特殊情况**您需要了解：

| 问题 | 症状 | 解决方案 |
|-------|---------|----------|
| **受限模式** | LSP 不启动，MCP 看不到项目 | 打开项目时按 "Trust and Continue" |
| **CWD = Zed 目录** | MCP 服务器从 Zed 安装目录启动，而非项目目录 | 通过 SQLite 回退修复（项目从 Zed 的数据库中获取，而非 CWD） |
| **MCP 不重启** | 终止进程后，工具无法工作 | 仅完全重启 Zed（File → Quit） |
| **项目解析错误** | 显示 gemma_agent 而非 MSCodeBase | 关闭所有 Zed 窗口，只打开所需项目 |

详情：**[ZED_WINDOWS_QUIRKS.md](../en/ZED_WINDOWS_QUIRKS.md)**

### 项目如何确定（无 LSP 时）

MCP 服务器按以下顺序确定当前项目：

1. **显式的 `project_root`** 来自工具参数
2. **SQLite `active_workspace_id`**（新增，首选！）— 读取 Zed 数据库中的 `scoped_kv_store`，
   其中存储了 `active_workspace_id` — 这是在 Windows 上唯一有效的
   机制。切换项目时即时生效。
3. **SQLite `workspaces`**（旧回退）— 如果未找到 `active_workspace_id`，
   则从 `workspaces` 表中选择最近的项目。
4. **LSP Bridge**（来自 LSP 的 JSON 文件 — **在 Windows 上无法工作**，LSP 不启动）
5. **环境变量中的 `PROJECT_PATH`**
6. **CWD** — **始终被自索引守卫拒绝**
7. **ext_root**（扩展目录）— 回退

> 在 Windows 上，步骤 1、4-5 通常不可用，因此项目通过
> SQLite `active_workspace_id`（步骤 2）确定。此机制在 Zed 中活动窗口
> 更改时自动切换项目。如果仍然不正确 — 关闭多余的 Zed 窗口。

---

## 🚀 可选：LM Studio

LM Studio 通过向量 embedding 提供更高质量的搜索。

1. 安装 [LM Studio](https://lmstudio.ai/)
2. 下载 embedding 模型（例如 `BAAI/bge-m3`）
3. 在端口 `1234` 上启动本地服务器
4. MCP 服务器将自动连接

验证：
```
intel_get_runtime_status()
```
响应应包含 `"embedding_provider": "lm_studio"` 和 `"lm_studio_at_1234": "online"`。

---

## 📄 卸载

```cmd
:: 运行卸载程序
uninstall.bat
```

或手动操作：
1. 从 `%APPDATA%\Zed\settings.json` 中删除 `mscodebase-intelligence` 部分
2. 删除扩展文件夹：
   ```
   %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence
   ```
3. 从项目根目录删除 `.codebase_indices`（如果存在）

---

## ❗ 故障排除

| 问题 | 原因 | 解决方案 |
|---------|-------|----------|
| **工具无响应** | MCP 服务器未运行 | File → Quit → 重新打开项目。日志：`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\` |
| **项目错误** | SQLite 选择了另一个工作区 | 关闭所有 Zed 窗口，只打开所需项目 |
| **0 个块** | 索引为空 | `intel_trigger_reindex()` — 等待 1-5 分钟 |
| **llama.cpp 离线** | Embedder 未启动 | 检查 `intel_get_runtime_status()`。日志：`扩展目录` + `.codebase_indices/logs/` |
| **LM Studio 离线** | 仅当使用 LM Studio 时 | 启动 LM Studio，检查端口 1234 |
| **settings.json 警告** | 过时的键（`lsp`，`mscodebase`） | 运行 `python install.py` — 它将清理 |
| **ModuleNotFoundError** | PYTHONPATH 未指向扩展 | `python install.py` — 自动修复 |

**数据存储位置：**
- **索引（LanceDB）：** `<project>/.codebase_indices/lancedb_v2/` — 代码块的向量数据库
- **日志：** `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`
- **项目记忆（ADR，known_issues）：** `<project>/.codebase_indices/intelligence/`

---

## 👨‍💻 开发（贡献者）

```bash
# 克隆
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence

# 以开发模式安装
pip install -e ".[dev]"

# 运行测试
pytest

# 在 Zed 中安装（更改后）
python install.py
```

详情：**[CONTRIBUTING.md](../../CONTRIBUTING.md)**

---

## 🔗 相关文档

| 文档 | 描述 |
|----------|-------------|
| [README.md](../../README.md) | 主文档，所有文档的导览，工具列表 |
| [ZED_WINDOWS_QUIRKS.md](../en/ZED_WINDOWS_QUIRKS.md) | **Windows 特殊说明：** 受限模式，CWD，MCP 重启 |
| [ARCHITECTURE.md](../en/ARCHITECTURE.md) | 项目架构，DI，分层 |
| [TELEMETRY.md](TELEMETRY.md) | 指标，ETA，数据收集 |
| [LSP_WONTFIX.md](../en/investigations/LSP_WONTFIX.md) | 为什么 LSP 在 Windows 上无法工作 |
| [CHANGELOG.md](../en/CHANGELOG.md) | 版本历史 |
| [CONTRIBUTING.md](../../CONTRIBUTING.md) | 开发，测试，PR |
