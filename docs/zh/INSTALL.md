# 为 Zed IDE 安装 MSCodebase Intelligence

<img src="../../logo/baner.svg" width="500" alt="MSCodeBase Banner">

[🇬🇧 English](../en/INSTALL.md) • [🇷🇺 Русский](../ru/INSTALL.md) • [🇨🇳 中文](INSTALL.md)

> **MSCodebase Intelligence** — 用于 Zed IDE 语义代码搜索的 MCP 服务器。
> 开发在 [github.com/ManSio/mscodebase-intelligence](https://github.com/ManSio/mscodebase-intelligence) 进行
> 安装后完全在本地运行。

---

## 🔧 系统要求

| 组件 | 要求 |
|-----------|-----------|
| **操作系统** | Windows 10+（主要支持）、macOS 12+、Linux |
| **Python** | 3.10+（推荐 3.11+） |
| **内存** | 4 GB（推荐 8+ GB） |
| **磁盘** | 500 MB（带模型则最多 2 GB） |
| **Zed IDE** | 最新版本 |
| **LM Studio**（可选） | 用于通过嵌入进行向量搜索 |

---

## 📥 快速安装

### 步骤 1：安装扩展

在**项目根目录**（`install.py`所在位置）打开终端并运行：

```bash
python install.py
```

> **Linux/macOS：** 也可以使用 `./install.sh`。
> **Windows：** 也可以使用 `install.bat`（双击或在cmd中运行）。

安装程序：
1. ✅ 检查 Python 和兼容性
2. ✅ 创建虚拟环境并安装依赖
3. ✅ 在 Zed 的 `settings.json` 中配置 MCP 服务器
4. ✅ 将源代码复制到已安装的扩展中
5. ✅ 创建 `uninstall.bat`

> **重要：** 安装程序将文件从当前目录复制到扩展中。
> 源代码的更改仅在 `python install.py` 后生效。

### 步骤 2：重启 Zed

**File → Quit**，然后重新打开项目。
简单的 `window: reload` **不足够** — MCP 服务器必须完全重启。

### 步骤 3：验证

打开 **Agent 面板**（`Ctrl+Shift+P` → `Agent Panel: Toggle`）并执行：

```
get_index_status()
```

您应该看到：

```
📂 <您的项目根目录>
🟢 **MSCodeBase** — active
📦 **块：** `1603` | **文件：** `114` | **符号：** `134`
🧠 **嵌入器：** 🌐 LM Studio
```

如果项目识别错误（显示的是其他项目而不是您的项目）— 关闭所有 Zed 窗口，只打开所需项目。

---

## 🧠 Windows 特性

在 Windows 上有**关键特性**需要了解：

| 问题 | 症状 | 解决方案 |
|----------|---------|---------|
| **受限模式** | LSP 无法启动，MCP 看不到项目 | 打开项目时点击"Trust and Continue" |
| **CWD = Zed 目录** | MCP 服务器从 Zed 安装目录启动，而非项目目录 | 通过 SQLite 回退修复（项目从 Zed 数据库而非 CWD 获取） |
| **MCP 不重启** | 进程被杀死后工具无法工作 | 仅完全重启 Zed（File → Quit） |
| **项目解析错误** | 显示 gemma_agent 而非 MSCodeBase | 关闭所有 Zed 窗口，只打开所需项目 |

更多详情：**[ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md)**

### 项目如何确定（无 LSP）

MCP 服务器按以下顺序确定当前项目：

1. **来自工具参数的显式 `project_root`**
2. **SQLite `active_workspace_id`**（新的，主要！）— 读取 Zed 数据库中的 `scoped_kv_store`，其中存储了 `active_workspace_id` — 在 Windows 上工作的**唯一**机制。切换项目时立即切换。
3. **SQLite `workspaces`**（旧的回退）— 如果未找到 `active_workspace_id`，则从 `workspaces` 表中选择最新项目。
4. **LSP 桥接**（来自 LSP 的 JSON 文件 — **在 Windows 上不起作用**，LSP 不启动）
5. **来自环境的 `PROJECT_PATH`**
6. **CWD** — **始终被自索引防护拒绝**
7. **ext_root**（扩展目录）— 回退

> 在 Windows 上，步骤 1、4-5 通常不可用，因此项目通过 SQLite `active_workspace_id`（步骤 2）确定。此机制在 Zed 中切换活动窗口时自动切换项目。如果识别仍然错误 — 关闭多余的 Zed 窗口。

---

## 🚀 可选：LM Studio

LM Studio 通过向量嵌入提供更高质量的搜索。

1. 安装 [LM Studio](https://lmstudio.ai/)
2. 下载嵌入模型（例如 `BAAI/bge-m3`）
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

或手动：
1. 从 `%APPDATA%\Zed\settings.json` 删除 `mscodebase-intelligence` 部分
2. 删除扩展文件夹：
   ```
   %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence
   ```
3. 从项目根目录删除 `.codebase_indices`（如果存在）

---

## ❗ 故障排除

| 问题 | 原因 | 解决方案 |
|----------|---------|---------|
| **工具无响应** | MCP 服务器未运行 | File → Quit → 重新打开项目。日志：`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\` |
| **错误项目** | SQLite 选择了其他工作区 | 关闭所有 Zed 窗口，只打开所需项目 |
| **0 个块** | 索引为空 | `intel_trigger_reindex()` — 等待 1-5 分钟 |
| **LM Studio 离线** | 服务器未运行 | 启动 LM Studio，检查端口 1234 |
| **settings.json 警告** | 过时的键（`lsp`、`mscodebase`） | 运行 `python install.py` — 它会清理 |
| **ModuleNotFoundError** | PYTHONPATH 未指向扩展 | `python install.py` — 会自动修复 |

**数据存储位置：**
- **索引（LanceDB）：** `<项目>/.codebase_indices/lancedb_v2/` — 包含代码块的向量数据库
- **日志：** `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`
- **项目记忆（ADR、known_issues）：** `<项目>/.codebase_indices/intelligence/`

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

# 安装到 Zed（更改后）
python install.py
```

更多详情：**[CONTRIBUTING.md](CONTRIBUTING.md)**

---

## 🔗 相关文档

| 文档 | 描述 |
|----------|----------|
| [README.md](README.md) | 主文档、所有文档的地图、工具列表 |
| [ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md) | **Windows 特性：** 受限模式、CWD、MCP 重启 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 项目架构、DI、分层 |
| [TELEMETRY.md](TELEMETRY.md) | 指标、ETA、数据收集 |
| [LSP_WONTFIX.md](../en/investigations/LSP_WONTFIX.md) | 为什么 LSP 在 Windows 上不起作用 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发、测试、PR |
