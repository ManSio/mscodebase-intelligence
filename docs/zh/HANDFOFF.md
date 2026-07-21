[🇬🇧 English](../en/HANDFOFF.md) • [🇷🇺 Русский](../ru/HANDFOFF.md) • [🇨🇳 中文](HANDFOFF.md)

> 这是一份给加入项目的开发者的文档。
> 描述了关键架构决策、Windows 陷阱
> 和调查结果，以便您不必重蹈覆辙。

---

## 🎯 项目简介

**MSCodeBase Intelligence** — 用于 Zed IDE 中语义代码搜索的 MCP 服务器。
完全本地运行：LanceDB（向量索引）+ ONNX E5-base INT8（进程内嵌入）+ llama.cpp GGUF（仅重排序器（reranker））+ OpenVINO INT8（可选）。

**关键数字：**
- 48 个 MCP 工具（19 core + 13 intel + 12 inline + 4 dev）— 包括 `query_graph`（Cypher 引擎）
- 11 个工具文件，DI 容器中的 16 个服务
- 索引：约 3000 个块（chunk），约 170 个文件，约 1550 个符号
- **PropertyGraph**：SQLite 图（15 种节点类型，27 种边类型），位于 `.codebase/graph.db`

---

## 🔑 主要发现：Windows 上的项目解析

**问题：** MCP 服务器需要知道 Zed 窗口中打开了哪个项目。
`ZED_WORKTREE_ROOT` 和 `current_dir` 在 Windows 上**无法工作**（Zed 错误）。
每个窗口启动自己的 MCP 进程，但环境变量未传递。

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
# → "D:\path\to\project"
```

**位置：** `src/mcp/server.py`，函数 `resolve_project_root()`，优先级 0。
**限制：** 如果一个项目有多个窗口 — MCP 不知道哪个是活动的。

→ **完整调查：** [`ACTIVE_WORKSPACE_RESOLUTION.md`](../en/investigations/ACTIVE_WORKSPACE_RESOLUTION.md)
  涵盖：6 种测试的 Zed 机制，内部 Rust API，SQLite 模式，4 种失败的方法。

---

## 🏗️ 关键架构决策

| 决策 | 动机 |
|----------|-----------|
| **DI 容器（ServiceCollection）** | 16 个服务，延迟解析，每个项目注册表 + PropertyGraph |
| **延迟解析活动索引器** | 如果 LSP 尚未写入桥接文件 — 选择第一个活动工作区 |
| **两阶段重新索引** | `intel_trigger_reindex` → job_id → `intel_get_job_status`（反垃圾邮件） |
| **异步锁用于文件 IO** | 保护对内存 JSON 文件的并发写入 |
| **ui_formatter** | 所有 48 个工具的统一 Markdown 风格（无原始 JSON） |

---

## 🔧 已损坏且不会修复的内容

| 组件 | 原因 | 状态 |
|-----------|--------|--------|
| **LSP 服务器**（`lsp_main.py`） | 独立 LSP — Zed 不注册自定义 LSP 名称。用于重命名的 LSP *客户端*（`lsp_client.py`）工作正常 | **WONTFIX**（仅独立） |
| **自动重启 MCP** | Zed 中没有重启崩溃的 context_server 的钩子 | **WONTFIX** |
| **`ZED_WORKTREE_ROOT`** | 在 Windows 上未设置（Zed 错误 #36019） | **通过 SQLite 解决** |

→ **完整 LSP 调查：** [`LSP_WONTFIX.md`](../en/investigations/LSP_WONTFIX.md)
  摘要：Zed 需要 Rust/WASM 适配器才能使用自定义 LSP。`settings.json` 无法
  注册新语言 — 只能覆盖现有语言的路径。
  测试了 8 种方法，全部失败。

---

## 🐛 已修复的错误（防止回归）

### 1. DebounceBatch 死锁

**文件：** `src/core/rate_limiter.py`
**症状：** 批量 `notify_change` 后 MCP 挂起 5 秒。
**原因：** `await` 在 `threading.Lock` 内部（不可重入）— 100% 死锁。
**修复：** 分离：在锁下决定 `should_flush`，`await` 本身 — 在释放锁之后。

### 2. 自索引守卫

MCP 服务器有时会索引自身（扩展源代码，约 500MB）。
**修复：** `base.py` 中的 `_is_self_index_path()` 检查 — 阻止 ext_root
和 Zed 安装目录，抛出 `ToolError`。

### 3. 项目记忆中的竞态条件

并发调用 `intel_log_incident` + `intel_add_memory_node` 会覆盖
JSON 文件。**修复：** `IntelligenceStore` 中的 `asyncio.Lock`。

---

## 🗄️ 数据存储位置

| 数据 | 路径 |
|------|------|
| 向量索引 | `<project>/.codebase_indices/lancedb_v2/` |
| 项目记忆（ADR，问题） | `<project>/.codebase_indices/intelligence/` |
| 日志 | `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\` |
| Zed 的数据库 | `%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite` |

---

## 📁 关键文件

| 文件 | 功能 |
|------|-------------|
| `src/mcp/server.py` | `resolve_project_root()`，所有 48 个工具的注册 |
| `src/mcp/tools/base.py` | `MCPTool`（基类），`resolve_indexer_for_request()` |
| `src/core/di_container.py` | 16 个服务，`ProjectIndexerRegistry` |
| `src/core/intelligence_layer.py` | 13 个 intel 工具，`ProjectIntelligenceLayer` |
| `src/core/indexer.py` | LanceDB，向量化，索引 |
| `src/core/searcher.py` | BM25 + Dense + RRF 混合搜索 |
| `src/utils/ui_formatter.py` | 所有工具的统一 Markdown 格式 |
| `src/core/error_handler.py` | `_format_success_response`，`error_boundary` |
| `src/core/rate_limiter.py` | DebounceBatch，SlidingWindowRateLimiter |

---

## ⚠️ Windows 陷阱

1. **受限模式** — 首次打开项目时按 "Trust and Continue"
2. **MCP 重启** — 仅 File → Quit（不是 `window: reload`，不是 kill）
3. **Git 子进程** — `GIT_ASKPASS=echo`，`CREATE_NO_WINDOW`，超时
4. **Windows 上的 LanceDB** — mmap 文件直到 `_safe_close()` + `gc.collect()` 才释放
5. **路径** — MCP：`src\core\file_guard.py`，终端：`src/core/file_guard.py`

---

## 🔗 相关文档

| 文档 | 关于 |
|----------|-------|
| `INSTALL.md` | 用户安装指南 |
| `ARCHITECTURE.md` | 完整架构（10 层） |
| `ZED_WINDOWS_QUIRKS.md` | Windows 特殊说明 |
| `investigations/LSP_WONTFIX.md` | 为什么 LSP 无法工作 |
| `investigations/ACTIVE_WORKSPACE_RESOLUTION.md` | SQLite active_workspace |
| `../../AGENTS.md` | Zed 中 AI 代理的规则 |
