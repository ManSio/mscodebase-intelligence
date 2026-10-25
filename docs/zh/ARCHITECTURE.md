<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[English](../en/ARCHITECTURE.md) · [Русский](../ru/ARCHITECTURE.md) · [中文](ARCHITECTURE.md)

# MSCodeBase Intelligence — 架构指南

> **更新于 2026-10-25。** 本文描述默认的 Phase 3 运行时：SQLite FTS5/BM25 +
> PropertyGraph。Embedding、rerank 和 LanceDB/vector path 是可选的，文中会
> 明确标注。

---

## 1. 设计目标

服务器让 AI 助手在本地获得有依据的代码库答案，而不强制依赖远程服务或大模型。

1. **本地优先。** 搜索、图和项目记忆无需网络。
2. **确定性优先于概率性。** 先尝试精确符号、路径和 BM25，再使用可选的语义层。
3. **失败要开放，不能沉默。** 缺少 embedder、空图或过期索引必须给出诊断，
   而不是编造答案。
4. **人类和 agent 共用一套契约。** Zed、脚本和测试使用同一 tool schema。
5. **可观测。** Runtime passport、index status、health report 和 logs 是正式
   工具，不是事后调试附属品。

## 2. 运行时概览

```text
Zed
 ├── built-in LSP (autocomplete, diagnostics)
 └── MCP client
      │
      ▼
 src/main.py (stdio) 或 src/remote_main.py (HTTP)
      │
      ▼
 server_factory.create_mcp_server()
      ├── create_service_collection()      DI container
      ├── register_all_tools()             64 registered tools
      └── notification / extension hooks
      │
      ├── Search        core/search
      ├── Index         core/indexing
      ├── Graph         core/graph.py + core/search/graph_adapter.py
      ├── Memory        core/intelligence
      ├── Writes        core/modification_guard.py + mcp/tools/write_tools.py
      └── Optional      providers/embedder, providers/reranker, LSP client
      │
      ▼
 Storage
      ├── <project>/.mscodebase/chunks.db       SQLite + FTS5
      ├── <data_root>/projects/<hash>/graph.db  PropertyGraph
      ├── <data_root>/projects/<hash>/intelligence/  memory, incidents
      └── <data_root>/logs/                     server logs
```

`<data_root>` 在 Windows 上是 `%LOCALAPPDATA%/mscodebase`，其他平台使用对应
位置。项目产物在仓库之外；`chunks.db` 是唯一留在项目目录内的存储。

## 3. 分层

| 层 | 职责 | 主要模块 |
|---|---|---|
| Entry | 进程启动、project root、stdio/HTTP | `src/main.py`, `src/remote_main.py` |
| Protocol | MCP server、lifecycle、hooks | `src/mcp/server.py`, `server_factory.py` |
| Tool | 薄适配器：校验、格式化、error boundary | `src/mcp/tools/*.py`, `server_tools.py` |
| Core | Search、indexing、graph、memory、write guards | `src/core/*` |
| Providers | 可选 embedders、rerankers、LSP | `src/providers/*`, `src/core/lsp_client.py` |
| Storage | SQLite/FTS5、PropertyGraph、JSON memory、logs | `chunk_store.py`, `graph.py`, `intelligence/` |

Tool layer 不实现 ranking 或 parsing，只解析 project-scoped service 并委托
给 core。

## 4. 入口与生命周期

- `src/main.py` — Zed 扩展使用的 stdio MCP server：解析 extension/project
  root、配置 logging、启动 server loop。
- `src/remote_main.py` — 同一 server 的 authenticated HTTP transport，可选，
  未配置时关闭。
- `src/mcp/server_factory.py` — 创建 server、DI container、注册 tools、
  notifications 和 shutdown handlers。
- `src/mcp/server_tools.py` — 注册和 tool allowlist。

另一个 Zed 窗口中的项目由 `ProjectIndexerRegistry` 隔离：每个项目有独立的
indexer/searcher/graph，带 LRU 上限和 resource monitoring。

## 5. 依赖注入

`src/core/di_container.py` 提供 `ServiceCollection` 和
`create_service_collection(project_root)`。服务是进程内 singleton：

- project root 和 parser；
- indexer/searcher 和可选 embedder；
- PropertyGraph 和 symbol index；
- `ProjectIndexerRegistry` / `MultiProjectSearcher`；
- rate limiter、circuit breaker、notification broker。

Tool class 通过 constructor injection 获取 collection，不直接创建 indexer 或
打开数据库。Shutdown 关闭资源并释放后台任务。

## 6. Tool 层

服务器注册 **64 个工具**：

- 31 个 core tool class（search、LSP、graph、analysis、write、lifecycle）；
- 16 个 `intel_*`；
- 13 个 inline diagnostic；
- 4 个 dev。

`execute_script` 是第 65 个可选工具，仅在
`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true` 时注册。默认 allowlist 暴露 **49**
个；`MSCODEBASE_MCP_TOOLS` 控制可见性（空值显示全部已注册工具）。

`codebase(action=...)` 是 index、git、write 的 hub。搜索有 `search_code` 和
`plan_search`，后者返回确定性计划（primary query、exact tokens、symbols、
concepts、intent）。

所有 tool 由 `error_boundary` 包裹：timeout、telemetry 和结构化错误，避免
挂住 MCP loop。

## 7. 索引流水线

```text
discover files
  → FileGuard (extensions, size, binaries, system dirs, .gitignore)
  → parser (Tree-sitter; language-specific extractors)
  → chunks + symbols + calls/imports/assignments/decorators/overrides
  → SQLiteChunkStore (text + FTS5) and PropertyGraph
```

规则：

- `experiments/**` **不进入索引**。其中是 frozen 面板和运行产物；索引它们曾
  让 BM25 返回面板本身而不是代码。文件仍保留在 git。
- Incremental indexing 在一个事务中更新文件的 chunks 和 graph rows。
- `MSCODEBASE_DENSE_OFF=true` 时完整 vector reindex 被有意阻止。文本用
  `scripts/reindex_text_only.py`，图用 `scripts/rebuild_graph.py`。
- `build_head` 只在完整成功索引后写入，便于与 git HEAD 比对 freshness。
- `FileGuard` 和 `SafePathManager` 在 parsing 前拒绝项目外路径和系统目录。

## 8. 存储

| Store | 路径 | 用途 |
|---|---|---|
| Chunk store | `<project>/.mscodebase/chunks.db` | 文本、metadata、FTS5 |
| Graph | `<data_root>/projects/<hash>/graph.db` | 符号、文件、typed edges |
| Memory | `<data_root>/projects/<hash>/intelligence/` | 项目记忆、事故、jobs |
| Logs | `<data_root>/logs/` | server/tool 诊断 |

LanceDB 是 legacy/optional vector store。默认 text-first path 不需要它，在
`MSCODEBASE_SQLITE_CHUNKS=true` 时也不是主要 candidate 来源。

## 9. 搜索集成

搜索是最大的 core 子系统。默认路径：

1. SQLite FTS5/BM25 candidates；
2. identifier-shaped 查询的可选 symbol/graph stage；
3. 可选 on-demand rerank；
4. exact-name boost 和 symbol deduplication；
5. BM25 分差足够大时，在 tool 层做 docs routing。

`core/search/engine.py` 中完整的 RRF/MMR/anchor pipeline 属于可选
dense/LanceDB path 或旧路径，不会静默应用到每个 Phase 3 查询。精确划分见
[SEARCH_PIPELINE.md](SEARCH_PIPELINE.md)。

## 10. Intelligence 与记忆

`core/intelligence/` 实现项目记忆和事故处理：

- ADR 和 known issues 以带状态和 evidence 的记录保存；
- 事故可记录、搜索，并基于 runtime data 预测；
- `verify-on-read` 可将记忆标记为 verified/refuted/superseded；
- retraction/supersede 保留历史，不删除。

记忆是本地、project-scoped 的，不是通用聊天日志。

## 11. 写入与安全

Write tools（`rename`、`move`、`safe_delete`、`replace`、`insert_before/after`）
操作符号，而不是裸文本。流程：

1. 解析 symbol 和 references；
2. 生成 impact summary；
3. load-bearing 文件要求 `ack_impact`；
4. preview；
5. 仅在 `apply=true` 时应用，然后刷新 chunks/graph。

跨文件 rename 可使用 basedpyright LSP；timeout 时回退 SymbolIndex。
`execute_script` 默认关闭；启用时使用 AST validation、import wrapper 和
subprocess sandbox。

## 12. 并发与多窗口

- 每个项目一个 indexer/searcher，通过 registry 解析。
- SQLite writes 由 chunk store lock 串行化；reads 跨线程安全。
- 后台索引使用 watchdog heartbeat 和 job state，agent 轮询而不阻塞编辑器。
- 外部进程使用 `Popen` + `communicate(timeout=...)`，不在 daemon thread 中用
  `capture_output`，避免 Windows pipe deadlock。
- Reindex fast-fail 返回明确的“索引重建中”错误，而不是挂起。

## 13. 故障与运维检查

| 现象 | 首先检查 | 修复 |
|---|---|---|
| Graph tools 无结果 | `graph.db` 的 nodes/edges | `python scripts/rebuild_graph.py` |
| 搜索返回 experiment docs | 索引含 `experiments/**` | reindex；FileGuard 已排除 |
| Docs 总是 miss | gold 是 `docs/en`，结果是 `docs/ru` | 按 basename 归一化 |
| Index stale | `codebase(action="index", path="status")` | `scripts/reindex_text_only.py` |
| Embedder missing | `debug_runtime_passport()` | text path 仍可用；配置 provider |
| Tools 不可见 | `MSCODEBASE_MCP_TOOLS` | 添加名称或设为空 |

## 14. 测试与验证

- `pytest tests/` — unit/integration suite；markers 区分 integration 和
  benchmark。
- `python scripts/smoke_e2e.py --project .` — 真实 embed/rerank/search，无
  mock，provider 可用时执行。
- `scripts/rebuild_graph.py` 和 `scripts/reindex_text_only.py` 是 graph/index
  drift 的官方修复路径。
- Search experiments 在 `experiments/`，含 frozen inputs 和 raw runs；README
  中的质量数字来源于此。

## 15. 相关文档

- [SEARCH_PIPELINE.md](SEARCH_PIPELINE.md) — retrieval、ranking、modes、limits。
- [ARCHITECTURE_DEEP.md](ARCHITECTURE_DEEP.md) — 历史深入内容和可选细节。
- [GRACEFUL_DEGRADATION.md](GRACEFUL_DEGRADATION.md) — provider 不可用时的行为。
- [INSTALL.md](INSTALL.md) — 安装与修复命令。
- [README.md](../../README.md) — 当前公开契约与测量质量。
