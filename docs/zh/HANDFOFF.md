<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

# MSCodeBase Intelligence — 架构与开发经验

[🇬🇧 English](../en/HANDFOFF.md) • [🇷🇺 Русский](../ru/HANDFOFF.md) • [🇨🇳 中文](HANDFOFF.md)

> 给加入项目的开发者的文档。
> 描述了关键的架构决策、Windows 的注意事项
> 和调查结果，以避免重蹈覆辙。

---

## 🎯 这是什么项目

**MSCodeBase Intelligence** — 用于 Zed IDE 语义代码搜索的 MCP 服务器。
完全在本地运行：LanceDB（向量索引）+ LM Studio（嵌入生成）。

**关键数据：**
- 43 个 MCP 工具（33 个核心 + 10 个 intel）
- 10 个工具文件，DI 容器中有 15 个服务
- 索引：约 1600 个块、约 115 个文件、约 180 个符号

---

## 🔑 主要发现：Windows 上的项目确定

**问题：** MCP 服务器需要知道 Zed 窗口中打开了哪个项目。
`ZED_WORKTREE_ROOT` 和 `current_dir` 在 Windows 上**不起作用**（Zed 缺陷）。
每个窗口启动自己的 MCP 进程，但环境变量不传递。

**解决方案：** 直接读取 Zed 的 SQLite 数据库：

```python
# 1. 从 scoped_kv_store 获取 active_workspace_id
conn.execute("""
    SELECT value FROM scoped_kv_store 
    WHERE namespace = 'multi_workspace_state'
""")
# → {"active_workspace_id": 2, ...}

# 2. 通过 ID 获取路径
conn.execute("""
    SELECT paths FROM workspaces WHERE workspace_id = ?
""", (active_id,))
# → "D:\路径\到\项目"
```

**位置：** `src/mcp/server.py`，函数 `resolve_project_root()`，优先级 0。
**限制：** 如果一个项目有多个窗口 — MCP 不知道哪个是活动的。

→ **完整调查：** [`ACTIVE_WORKSPACE_RESOLUTION.md`](../en/investigations/ACTIVE_WORKSPACE_RESOLUTION.md)
  包含：检查了 6 种 Zed 机制、内部 Rust API、SQLite 模式、4 种失败方法。

---

## 🏗️ 关键架构决策

| 决策 | 动机 |
|---------|-----------|
| **DI 容器（ServiceCollection）** | 15 个服务，惰性解析，按项目注册表 |
| **延迟解析活动索引器** | 如果 LSP 未及时写入桥接 — 接管第一个活跃工作区 |
| **两阶段重新索引** | `intel_trigger_reindex` → job_id → `intel_get_job_status`（反垃圾邮件） |
| **asyncio.Lock 用于文件 IO** | 防止并发写入 JSON 内存文件时的竞态 |
| **ui_formatter** | 所有 43 个工具的统一 Markdown 风格（无原始 JSON） |

---

## 🔧 什么坏了且不会被修复

| 组件 | 原因 | 状态 |
|-----------|---------|--------|
| **LSP 服务器**（`lsp_main.py`） | Zed 不注册自定义 LSP 名称（需要 Rust/WASM） | **WONTFIX** |
| **自动重启 MCP** | Zed 没有用于重启崩溃的 context_server 的钩子 | **WONTFIX** |
| **`ZED_WORKTREE_ROOT`** | 在 Windows 上未设置（Zed bug #36019） | **通过 SQLite 绕过** |

→ **完整 LSP 调查：** [`LSP_WONTFIX.md`](../en/investigations/LSP_WONTFIX.md)
  实质：Zed 需要 Rust/WASM 适配器用于自定义 LSP。`settings.json` 无法注册新语言 — 只能覆盖现有语言的路径。
  检查了 8 种方法，全部失败。

---

## 🐛 已修复的缺陷（以防回退）

### 1. DebounceBatch 死锁

**文件：** `src/core/rate_limiter.py`
**症状：** 在一批 `notify_change` 后约 5 秒 MCP 挂起。
**原因：** `threading.Lock` 内部的 `await`（不可重入）— 100% 死锁。
**修复：** 分离：在锁下决定 `should_flush`，`await` 本身在锁后。

### 2. 自索引防护

MCP 服务器有时会索引自身（扩展源代码，约 500MB）。
**修复：** `base.py` 中的 `_is_self_index_path()` 检查 — 阻止 ext_root
和 Zed 安装目录，抛出 `ToolError`。

### 3. 项目记忆中的竞态条件

并发的 `intel_log_incident` + `intel_add_memory_node` 调用会覆盖
JSON 文件。**修复：** `IntelligenceStore` 中的 `asyncio.Lock`。

---

## 🗄️ 数据存储位置

| 数据 | 路径 |
|--------|------|
| 向量索引 | `<项目>/.codebase_indices/lancedb_v2/` |
| 项目记忆（ADR, issues） | `<项目>/.codebase_indices/intelligence/` |
| 日志 | `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\` |
| Zed 数据库 | `%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite` |

---

## 📁 关键文件

| 文件 | 功能 |
|------|-----------|
| `src/mcp/server.py` | `resolve_project_root()`、所有 43 个工具的注册 |
| `src/mcp/tools/base.py` | `MCPTool`（基类）、`resolve_indexer_for_request()` |
| `src/core/di_container.py` | 15 个服务、`ProjectIndexerRegistry` |
| `src/core/intelligence_layer.py` | 10 个 intel 工具、`ProjectIntelligenceLayer` |
| `src/core/indexer.py` | LanceDB、向量化、索引 |
| `src/core/searcher.py` | BM25 + Dense + RRF 混合搜索 |
| `src/utils/ui_formatter.py` | 所有工具的统一 Markdown 格式 |
| `src/core/error_handler.py` | `_format_success_response`、`error_boundary` |
| `src/core/rate_limiter.py` | DebounceBatch、SlidingWindowRateLimiter |

---

## ⚠️ Windows 注意事项

1. **受限模式** — 首次打开项目时点击"Trust and Continue"
2. **MCP 重启** — 仅 File → Quit（不是 `window: reload`、不是 kill）
3. **Git 子进程** — `GIT_ASKPASS=echo`、`CREATE_NO_WINDOW`、超时
4. **Windows 上的 LanceDB** — mmap 文件在 `_safe_close()` + `gc.collect()` 前不释放
5. **路径** — MCP：`src\core\file.py`，终端：`src/core/file.py`

---

## 🔗 相关文档

| 文档 | 内容 |
|----------|-------|
| `INSTALL.md` | 用户安装指南 |
| `ARCHITECTURE.md` | 完整架构（10 层） |
| `ZED_WINDOWS_QUIRKS.md` | Windows 特性 |
| `../en/investigations/LSP_WONTFIX.md` | 为什么 LSP 不起作用 |
| `../en/investigations/ACTIVE_WORKSPACE_RESOLUTION.md` | SQLite active_workspace |
| `../../AGENTS.md` | Zed 中 AI 代理的规则 |
