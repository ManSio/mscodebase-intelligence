<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](../en/FAQ.md) • [🇷🇺 Русский](../ru/FAQ.md) • [🇨🇳 中文](FAQ.md)

# FAQ — MSCodeBase Intelligence

> 常见问题解答。基于实际开发和运维经验。

---

## 📦 安装与启动

### MCP服务器安装后无响应

**原因：** Zed未重启。`window: reload` 不够。
**解决方法：** File → Quit → 重新打开项目。

日志：`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`

### 运行 `python install.py` 后无变化

**原因：** 安装程序已将文件复制到扩展目录，但MCP服务器仍使用旧代码运行。
**解决方法：** File → Quit → 重新打开项目。只有完全重启才能重启MCP。

### 索引为空（0个块）

**解决方法：** 在Agent Panel中执行 `intel_trigger_reindex()`。等待1-5分钟。
通过 `intel_get_job_status(<job_id>)` 跟踪进度。

---

## 🔍 搜索与工具

### `search_code` 返回0个结果

**可能原因：**
- 索引为空 → 见上方
- LM Studio未运行 → `intel_get_runtime_status()` 会显示 "offline"
- 错误的项目 → 检查 `get_index_status()` 输出

### `get_index_status()` 显示错误项目

**原因：** 通过SQLite进行项目解析 — 如果Zed中打开了多个项目，
可能选择了错误的项目。尤其是在 Windows 上，`ZED_WORKTREE_ROOT` 未被设置。

**解决方法：** 关闭所有Zed窗口，只打开需要的项目。
详情：`../en/investigations/ACTIVE_WORKSPACE_RESOLUTION.md`

### 工具返回原始JSON

**如果来自旧版本：** 已修复。在提交 `05de324`（2026-07-05）之后，
所有43个工具输出可读的Markdown。
**解决方法：** 运行 `python install.py` 并重启Zed。

---

## 🪟 Windows

### LSP无法启动 (mscodebase-lsp)

**原因：** Windows上的Zed无法注册自定义LSP名称。
需要Rust/WASM适配器。`settings.json` 无法解决。
**状态：** WONTFIX。MCP服务器在无LSP情况下功能完整。
详情：`../en/investigations/LSP_WONTFIX.md`

### Zed显示 "Restricted Mode"（限制模式）

**解决方法：** 点击 "Trust and Continue"。勾选 "Trust all projects in..."
否则LSP不会启动，MCP无法看到项目。

### MCP无法自动重启

**解决方法：** 仅限 File → Quit → 重新打开项目。
Windows上的Zed不支持自动重启。

### 项目解析为 "ext_root"（自索引）

**原因：** `resolve_project_root()` 无法通过SQLite找到项目。
**解决方法：** 确保项目已在Zed中打开。检查 `LocalAPPDATA/Zed/db/0-stable/db.sqlite`。
如果为空 — 可能是限制模式在阻止。

---

## ⚡ 性能

### 搜索缓慢 (>10秒)

**可能原因：**
- LM Studio在弱机上运行（检查 `intel_get_telemetry()` → ping）
- 索引未优化（运行 `intel_trigger_reindex()`）
- `search_code` 中的 `limit` 过高（建议6-10）

### LLM Ping > 2000ms

**解决方法：** 检查LM Studio。确保已加载嵌入模型（如 `BAAI/bge-m3`）。
不要通过LM Studio使用LLM模型进行嵌入 — 它们速度很慢。

### 内存占用 > 500 MB

**正常现象：** LanceDB使用mmap文件。Windows将其保存在内存中。
**解决方法：** 重启MCP释放内存（File → Quit）。

---

## 🐛 错误与问题

### `ModuleNotFoundError: No module named 'src'`

**原因：** PYTHONPATH未指向扩展目录。
**解决方法：** 运行 `python install.py` — 它会设置正确的PYTHONPATH。

### `ToolError: Refusing to index self`

**原因：** 自索引保护 — MCP阻止索引自己的源代码。
**解决方法：** 在Zed中打开另一个项目（不是扩展本身）。

### 批量 notify_change 后MCP卡死

**在旧版本中（2026-07-05之前）：** DebounceBatch中的死锁。
**已修复。** 如果仍然发生 — 检查版本（`debug_runtime_passport` → BUILD_ID）。
解决方法：File → Quit。

---

## 🔗 相关文档

| 文档 | 说明 |
|----------|-------------|
| `INSTALL.md` | 用户安装指南 |
| `ARCHITECTURE.md` | 项目架构（10层） |
| `ZED_WINDOWS_QUIRKS.md` | Windows特有说明 |
| `HANDFOFF.md` | 开发经验，架构决策 |
