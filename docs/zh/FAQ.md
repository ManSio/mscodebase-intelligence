<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](../en/FAQ.md) • [🇷🇺 Русский](../ru/FAQ.md) • [🇨🇳 中文](FAQ.md)

# FAQ — MSCodeBase Intelligence

> 常见问题解答。基于实际的开发和运维经验。

---

## 📦 安装与启动

### 什么是 llama.cpp，为什么需要它？

**llama.cpp** 是一个内置的 embedding 和重排序提供者，
通过 `install.py` 自动安装。它会下载
GGUF 模型（bge-m3 Q4_K_M 417 MB 和 bge-reranker-v2-m3 Q4_K_M 418 MB）
并在本地运行 `llama-server.exe`。不需要像 LM Studio 这样的外部服务。
仅消耗 227 MB RAM 而非 1200 MB — 节省 5.3 倍。

### 安装后 MCP 服务器无响应

**原因：** 未重启 Zed。`window: reload` 不够。
**解决方案：** File → Quit → 重新打开项目。

日志：`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`

### 运行 `python install.py` 后没有任何变化

**原因：** 安装程序将文件复制到了扩展目录，但 MCP 服务器已在运行旧代码。
**解决方案：** File → Quit → 重新打开项目。只有完全重启才能重启 MCP。

### 索引为空（0 个块）

**解决方案：** 在 Agent Panel 中运行 `intel_trigger_reindex()`。等待 1-5 分钟。
通过 `intel_get_job_status(<job_id>)` 跟踪进度。

---

## 🔍 搜索与工具

### `search_code` 返回 0 个结果

**原因：**
- 索引为空 → 见上文
- Embedder 未运行 → `intel_get_runtime_status()` 显示 "offline"
- 项目错误 → 检查 `get_index_status()` 输出

### `get_index_status()` 显示错误的项目

**原因：** 通过 SQLite 进行项目解析 — 如果在 Zed 中打开了多个项目，
它可能选择了错误的项目。尤其在 Windows 上，`ZED_WORKTREE_ROOT` 未设置。

**解决方案：** 关闭所有 Zed 窗口，只打开所需项目。
详情：`../en/investigations/ACTIVE_WORKSPACE_RESOLUTION.md`

### 工具返回原始 JSON

**如果来自旧版本：** 已修复。在提交 `05de324`（2026-07-05）之后，
所有 57 个工具输出可读的 Markdown。
**解决方案：** 运行 `python install.py` 并重启 Zed。

---

## 🪟 Windows

### LSP 无法启动（mscodebase-lsp）

**原因：** Windows 上的 Zed 无法注册自定义 LSP 名称。
需要 Rust/WASM 适配器。`settings.json` 无能为力。
**状态：** WONTFIX。MCP 服务器无需 LSP 即可完全工作。
详情：`../en/investigations/LSP_WONTFIX.md`

### Zed 显示 "Restricted Mode"

**解决方案：** 点击 "Trust and Continue"。勾选 "Trust all projects in..."。
否则 LSP 不会启动，MCP 将看不到项目。

### MCP 不会自动重启

**解决方案：** 仅 File → Quit → 重新打开项目。
Zed 在 Windows 上不支持自动重启。

### 项目解析为 "ext_root"（自索引）

**原因：** `resolve_project_root()` 无法通过 SQLite 找到项目。
**解决方案：** 确保项目在 Zed 中打开。检查 `LocalAPPDATA/Zed/db/0-stable/db.sqlite`。
如果为空 — 可能是受限模式阻止了它。

---

## ⚡ 性能

### 搜索慢（>10 秒）

**原因：**
- llama.cpp 或 embedder 未就绪（检查 `intel_get_runtime_status()`）
- 索引未优化（运行 `intel_trigger_reindex()`）
- `search_code` 中的 `limit` 太高（建议 6-10）

### LLM Ping > 2000ms

**解决方案：** 检查 embedder 状态。如果使用 llama.cpp：
`curl http://127.0.0.1:8080/health`。如果使用 LM Studio：
确保已加载 embedding 模型（例如 `BAAI/bge-m3`）。

### 内存 > 500 MB

**正常：** LanceDB 使用 mmap 文件。Windows 将其保留在内存中。
**解决方案：** 重启 MCP 以释放内存（File → Quit）。

---

## 🐛 错误与故障

### `ModuleNotFoundError: No module named 'src'`

**原因：** PYTHONPATH 未指向扩展目录。
**解决方案：** 运行 `python install.py` — 它会设置正确的 PYTHONPATH。

### `ToolError: Refusing to index self`

**原因：** 自索引守卫 — MCP 保护自身不被索引其自己的源代码。
**解决方案：** 在 Zed 中打开其他项目（而不是扩展目录）。

### 批量 notify_change 后 MCP 挂起

**在旧版本中（2026-07-05 之前）：** DebounceBatch 死锁。
**已修复。** 如果仍然发生 — 检查版本（`debug_runtime_passport` → BUILD_ID）。
解决方案：File → Quit。

---

## 🔗 相关文档

| 文档 | 描述 |
|----------|-------------|
| [INSTALL.md](INSTALL.md) | 用户安装指南 |
| [ARCHITECTURE.md](../en/ARCHITECTURE.md) | 项目架构（10 层） |
| [ZED_WINDOWS_QUIRKS.md](../en/ZED_WINDOWS_QUIRKS.md) | Windows 特殊说明 |
| [HANDFOFF.md](HANDFOFF.md) | 开发经验，架构决策 |
