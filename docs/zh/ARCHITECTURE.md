<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](../en/ARCHITECTURE.md) • [🇷🇺 Русский](../ru/ARCHITECTURE.md) • [🇨🇳 中文](ARCHITECTURE.md)

# MSCodeBase Intelligence — 架构指南

> **版本：** 3.3.9  
> **最后更新：** 2026-07-21  
> **架构：** 4 层架构 + 图原生 PropertyGraph 层 + 数据流层（入口点 → MCP 服务器/DI → 工具类 → 核心业务逻辑 → PropertyGraph → 数据流）带多窗口注册表 + DocSync

---

## 目录

1. [核心原则](#1-核心原则)
2. [分层架构](#2-分层架构)
3. [DI 容器（ServiceCollection）](#3-di-容器)
4. [工具层（18 核心 + 13 intel + 7 内联 + 3 开发 + 1 可选 = 42 个）](#4-工具层)
5. [PropertyGraph 层（v3.0）](#5-propertygraph-层-v30)
6. [Cypher 查询引擎（v3.0）](#6-cypher-查询引擎-v30)
7. [错误处理](#7-错误处理)
8. [速率限制与弹性](#8-速率限制与弹性)
9. [数据流：请求 → 响应](#9-数据流)
10. [Windows 特定处理](#10-windows-特定处理)
11. [多窗口注册表（v2.3+）](#11-多窗口注册表-v23)
12. [测试策略](#12-测试策略)

---

## 1. 核心原则

```
┌──────────────────────────────────────────────────────────────────┐
│              四层架构                                              │
│                                                                  │
│  第 1 层: main.py / lsp_main.py  （入口点，最简）                   │
│  第 2 层: mcp/server.py          （DI 路由，工具注册）              │
│  第 3 层: mcp/tools/*.py         （18 核心 + 7 内联 + 3 开发）      │
│  第 4 层: core/*.py              （纯业务逻辑）                    │
└──────────────────────────────────────────────────────────────────┘
```

**关键规则：**
- **核心层没有 MCP 导入。** 它是纯 Python 业务逻辑。
- **工具层从不创建依赖。** 一切来自 DI。
- **server.py 仅注册** — 没有逻辑，没有格式化，没有 try/except。
- **依赖关系向下流动：** Main ← Server ← Tools ← Core。

---

## 2. 分层架构

### 2.0 十层运行时架构（v2.4）

```
 Layer 0: Filesystem                  — 磁盘上有哪些文件？
 Layer 1: SystemArtifacts             — 这是系统路径吗？
 Layer 2: Bridge (LSP→MCP)           — LSP 报告了哪个项目？
 Layer 3: Registry (IndexerRegistry)  — 哪个 Indexer 拥有此项目？
 Layer 4: StateMachine (ProjectState) — 项目处于什么状态？
 Layer 5: RuntimeCoordinator          — 可以执行此请求吗？
 Layer 6: ProjectContext              — 项目当前的状态如何？
 Layer 7: Passport                    — 当前运行的是哪个进程？
 Layer 8: Intel Layer                 — 如何处理这些信息？
 Layer 9: MCP Tools / AI Agent        — 给用户的回答
```

**数据流：**
```
Filesystem → SystemArtifacts → Bridge → Registry → StateMachine
                                                          ↓
MCP Tools ← Intel Layer ← ProjectContext ← RuntimeCoordinator
```

**关键规则：** 工具不直接访问 Registry、Bridge 或 Passport。
一切通过 `RuntimeCoordinator.can_execute()` + `ProjectContext.capture()`。

### 2.1 入口点

| 文件 | 协议 | 用途 |
|------|----------|---------|
| `src/main.py` | MCP STDIO | Zed Chat 中的 AI 助手 |
| `src/lsp_main.py` *（已删除）* | LSP STDIO | 已被 LSP 客户端 `src/core/lsp_client.py` 替代 |

两者都使用相同的 `create_service_collection()` 工厂。

### 2.2 MCP 服务器

| `src/mcp/server.py` | **~220 行**（重构前为 3,100 行）。

职责：
1. 解析项目根目录（`resolve_project_root()`）
2. 创建 DI 容器（`create_service_collection()`）
3. 注册 18 核心 + 13 intel + 7 内联 + 3 开发 + 1 可选 = 42 个工具
4. 注册系统提示（mscodebase-rules）

**此处没有业务逻辑。** 每个工具都是从 `mcp/tools/` 导入的。

### 2.3 工具层

`src/mcp/tools/*.py` — **14 个文件：18 个核心工具 + 7 个内联 + 3 个开发 + 1 个可选（Hub & Spoke：codebase + execute_script + 17 个原生）。**

每个工具：
- 继承自 `MCPTool`（ABC）
- 通过构造函数接收依赖项（构造函数注入）
- 有且仅有一个入口点：`async def execute(**kwargs) -> dict`
- 使用 `@error_boundary(tool_name, timeout_ms)` 装饰

```python
class SearchCodeTool(MCPTool):
    """search_code — 语义代码搜索。"""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="search_code")
        self.searcher = services.resolve(Searcher)
        self.symbol_index = services.resolve(SymbolIndex)

    @error_boundary("search_code", timeout_ms=15000)
    async def execute(
        self,
        query: str,
        mode: str = "auto",
        limit: int = 6,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        self.require_index()  # 检查索引就绪状态
        # ... 搜索逻辑
```

### 2.4 核心层

`src/core/*.py` — **30 个纯业务逻辑文件。**

关键模块：

| 模块 | 路径 | 用途 |
|--------|------|---------|
| `di_container.py` | `src/core/di_container.py` | DI 容器（15+ 服务） |
| `error_handler.py` | `src/core/error_handler.py` | ToolError + error_boundary |
| `rate_limiter.py` | `src/core/rate_limiter.py` | DebounceBatch + CircuitBreaker |
| `engine.py` | `src/core/search/engine.py` | 混合搜索（BM25 + Dense + FTS5 + RRF） |
| `graph.py` | `src/core/graph.py` | PropertyGraph — SQLite 属性图 |
| `graph_adapter.py` | `src/core/search/graph_adapter.py` | 包装 PropertyGraph 的 SymbolIndexAdapter |
| `cypher_engine.py` | `src/core/search/cypher_engine.py` | PropertyGraph 的 Cypher→SQL 引擎 |
| `indexer.py` | `src/core/indexing/indexer.py` | LanceDB 向量存储 + 索引化流水线 |
| `symbol_index.py` | `src/core/indexing/symbol_index.py` | 调用图（BFS, PageRank） |
| `parser.py` | `src/core/indexing/parser.py` | Tree-sitter AST 解析器（16 种语言） |
| `file_guard.py` | `src/core/indexing/file_guard.py` | .gitignore + 扩展过滤器 |
| `db_manager.py` | `src/core/indexing/db_manager.py` | LanceDB 表生命周期（PID 锁，重新索引守卫） |
| `fts5_mixin.py` | `src/core/search/fts5_mixin.py` | FTS5 全文搜索 mixin |
| `scoring.py` | `src/core/search/scoring.py` | RRF + MMR 多样性评分 |
| `layer.py` | `src/core/intelligence/layer.py` | Intel 层（13 个 intel_* 工具） |
| `runtime_coordinator.py` | `src/core/runtime_coordinator.py` | ExecutionVerdict + can_execute() |
| `project_context.py` | `src/core/intelligence/project_context.py` | 项目状态快照 |
| `llama_runner.py` | `src/providers/reranker/llama_runner.py` | llama-server.exe（重排序器）生命周期 |
| `remote_embedder.py` | `src/providers/embedder/remote_embedder.py` | ONNX E5-small INT8 嵌入器 + LM Studio/Ollama 回退 |
| `doc_sync_engine.py` | `src/core/doc_sync_engine.py` | 自动同步文档与代码（重命名钩子） |

### 2.5 搜索引擎（v3.3）

```
┌─────────────────────────────────────────────────────────┐
│   搜索流水线（engine.py）                                  │
│                                                          │
│   query_str → embed() → BM25 → FTS5 → 3-way RRF → MMR  │
│                        ↕                                │
│   MultiSignalScorer: api_signature, graph_diffusion,     │
│   module_proximity, cochange_boost                       │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│   PropertyGraph（graph.py）                               │
│   SQLite（WAL + mmap），节点/边，JSON 属性                 │
│   — 15 个节点标签（File, Function, Class, Variable...）  │
│   — 27 种边类型（CALLS, DEFINES, ASSIGNED_FROM, ...）    │
│   — Cypher 查询引擎（MATCH→SQL）                         │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│   数据流层（v3.2.0）                                      │
│                                                          │
│   1. 统一 Walker — 一次 Tree-sitter 解析 → 调用 +         │
│      赋值。带内容哈希的解析缓存。                          │
│   2. 条件流 — ASSIGNED_FROM 边具有                        │
│      condition_path（if/for/while/try/except）            │
│   3. 仅过程内 — 在函数体内部                              │
│   4. 16 种语言：Python, Rust, TS, TSX, Go, JS,           │
│      Java, C#, Ruby, PHP, Kotlin, Swift, C, C++,        │
│      Scala, Dart                                        │
└─────────────────────────────────────────────────────────┘
```

### 2.6 嵌入器（Embedder）：E5-small ONNX（进程内）

MCP 服务器现在使用 multilingual-e5-small 通过 ONNX Runtime（CPU，进程内）作为其主要嵌入器（embedder）：

- **模型：** `intfloat/multilingual-e5-small`（384 维）
- **运行时：** ONNX（CPU，不需要 GPU）
- **架构：** 进程内 — 无需外部 HTTP 服务器
- **性能：** ~37 ch/s（之前使用 BGE-M3 为 18 i/s）
- **RAM：** ~265 MB（之前为 285 MB + VRAM）
- **配置：** `EMBEDDING_DIMENSION=384`，`EMBEDDING_PROVIDER=e5_onnx`

重排序器（reranker）仍然通过 llama-server 运行（1 个进程，不是 2 个）。

传统的回退（fallback）提供者（provider）（LM Studio、Ollama、远程 ONNX）仍然可通过 `remote_embedder.py` 用于自定义配置。

---

## 3. DI 容器

### 3.1 ServiceCollection

```python
# src/core/di_container.py

services = ServiceCollection()

# 注册单例：
services.add_singleton(Indexer, indexer_instance)

# 注册懒工厂：
services.add_factory(Searcher, lambda s: Searcher(s.resolve(Indexer), ...))

# 解析：
indexer = services.resolve(Indexer)  # 每次都是同一个实例
```

### 3.2 已注册服务（15 个）

| # | 服务 | 类型 | 创建者 |
|---|---------|------|------------|
| 1 | Path (project_root) | 单例 | 显式 |
| 2 | Path (db_path) | 单例 | `_generate_unique_db_path()` |
| 3 | CodeParser | 单例 | `CodeParser()` |
| 4 | FileGuard | 单例 | `FileGuard(project_root)` |
| 5 | RemoteEmbedder | 单例 | `RemoteEmbedder()` |
| 6 | SymbolIndex | 单例 | `SymbolIndex()` |
| 7 | SlidingWindowRateLimiter | 单例 | `SlidingWindowRateLimiter()` |
| 8 | CircuitBreaker | 单例 | `CircuitBreaker(name="lm_studio")` |
| 9 | ProjectRegistry | 单例 | `ProjectRegistry()` |
| 10 | MultiProjectSearcher | 单例 | `MultiProjectSearcher(embedder, registry)` |
| 11 | ResourceMonitor | 单例 | `get_global_resource_monitor()` |
| 12 | ResourceMonitorKey | 单例 | `ResourceMonitor`（共享） |
| 13 | ProjectIndexerRegistry | 单例 | `ProjectIndexerRegistry(max_cached=5)` |
| 14 | NotificationBroker | 单例 | `NotificationBroker()` |
| 15 | IndexerFactoryKey | 工厂 | `_create_indexer_for_path` |

---

## 4. 工具层

### 4.1 工具注册

在 `src/mcp/server_tools.py` 中：

```python
def register_all_tools(mcp, services):
    tool_classes = [
        # 搜索（3 个）
        SearchCodeTool, GetSymbolInfoTool, ImpactAnalysisTool,
        # Hub: codebase（按 action 多路复用 — write/index/git/notify）
        CodebaseTool,
        # Spoke: E2B 沙箱
        ExecuteScriptTool,
        # 分析（5 个）
        StructuralSearchTool, GetRepoMapTool, GetRepoRankTool,
        ScanChangesTool, GenerateChunkSummariesTool,
        # 图（3 个 — Phase 2: graph_query 多路复用 cypher + related + flow）
        CrossRepoSearchTool, CrossProjectDepsTool, GraphQueryTool,
        # 调查（3 个）
        GetBugCorrelationTool, GetHotspotsTool, FindSimilarBugsTool,
        # 生命周期（3 个）
        SubmitBackgroundTaskTool, GetTaskStatusTool, VerifyActionTool,
    ]
    # +13 个 intel_* 工具 + 7 个内联诊断 + 3 个开发 + 1 个可选
    # 总计：42 个已注册（18 核心 + 13 intel + 7 内联 + 3 开发 + 1 可选）
```

**工具可见性过滤器：** 默认显示 ~16 个工具。设置 `MSCODEBASE_MCP_TOOLS=""` 以显示全部 42 个。

### 4.2 按组分组的全部工具

| 组 | 文件 | 工具 |
|-------|------|-------|
| **搜索**（3 个） | `search_tools.py` | search_code, get_symbol_info, impact_analysis |
| **Hub: codebase**（1 个） | `codebase_tool.py` | codebase(action=rename/move/delete/replace/insert/notify/index/git) |
| **Spoke: E2B**（1 个） | `codebase_tool.py` | execute_script(code) |
| **分析**（5 个） | `analysis_tools.py` | structural_search, get_repo_map, get_repo_rank, scan_changes, generate_chunk_summaries |
| **图**（3 个） | `graph_tools.py` | cross_repo_search, cross_project_deps, graph_query |
| **调查**（3 个） | `investigation_tools.py` | get_bug_correlation, get_hotspots, find_similar_bugs |
| **生命周期**（3 个） | `lifecycle_tools.py` | submit_background_task, get_task_status, verify_action |
| **写入**（1 个） | `write_tools.py` | codebase(action={rename,move,delete,replace,insert,impact}) |
| **索引**（1 个） | `indexing_tools.py` | get_index_status, notify_change, watcher_status |
| **Git**（1 个） | `git_tools.py` | git(action={log,history,branch}) |
| **文档**（1 个） | `doc_tools.py` | generate_docs, bump_version, auto_update_docs, install_git_hooks |
| **元**（1 个） | `meta_tools.py` | get_index_status, get_index_progress, get_index_timeline, get_health_report, get_logs |
| **系统**（1 个） | `system_tools.py` | read_live_file, get_health_report, get_logs |
| **智能层**（13 个） | `intelligence/layer.py` | intel_get_runtime_status, intel_get_job_status, intel_code_topology, intel_log_incident, intel_get_project_memory, intel_add_memory_node, intel_get_hotspots, intel_analyze_incident, intel_predict_root_cause, intel_trigger_reindex, intel_get_project_context, intel_explain_project_state, intel_get_telemetry, intel_tool_health |
| **诊断内联**（7 个） | `server_tools.py` | debug_runtime_passport, get_runtime_counters, intel_execution_timeline, get_health_report, get_logs, read_live_file, stale_detector |

> **总计：** 42 个已注册（18 核心 + 13 intel + 7 内联 + 3 开发 + 1 可选）。默认可见：~16 个。显示全部：`MSCODEBASE_MCP_TOOLS=""`。

---

## 5. PropertyGraph 层（v3.0）

PropertyGraph 是系统的语义骨干，在 `.codebase/graph.db` 中存储：

| 组件 | 文件 | 用途 |
|-----------|------|---------|
| **PropertyGraph** | `src/core/graph.py` | SQLite（WAL + mmap），15 个节点标签，27 种边类型 |
| **SymbolIndexAdapter** | `src/core/search/graph_adapter.py` | 将 PropertyGraph 包装为只读 SymbolIndex |
| **CypherEngine** | `src/core/search/cypher_engine.py` | Cypher → SQL 转换（MATCH→JOIN, RETURN→SELECT） |
| **RouteExtractor** | `src/core/graph.py` | 从 AST 中提取 HTTP 路由 |

**支持的图谱操作：**

| 操作 | Cypher 示例 | 用途 |
|-----------|-------------|---------|
| 调用者 | `MATCH (c)-[:CALLS]->(f) WHERE f.name='func' RETURN c` | "谁调用了 func？" |
| 被调用者 | `MATCH (f)-[:CALLS]->(c) WHERE f.name='func' RETURN c` | "func 调用了谁？" |
| 定义者 | `MATCH (c)-[:DEFINES]->(f) WHERE f.name='func' RETURN c` | "func 在哪里定义的？" |
| 赋值来源 | `MATCH (s)-[e:ASSIGNED_FROM]->(t) WHERE t.name='x' RETURN s` | "x 从哪里来？" |
| 数据流图 | `MATCH (s)-[*1..3]->(t) WHERE ...` | 多跳数据流追踪 |
| 拓扑 | `intel_code_topology(symbol)` | 架构调用图 |

---

## 6. Cypher 查询引擎（v3.0）

`CypherEngine` 将 Cypher AST 转换为 SQL 查询：

**支持的 Cypher 模式：**

| 模式 | SQL 等效 | 示例 |
|---------|-------------|---------|
| `MATCH (n)` | `SELECT * FROM nodes` | 所有节点 |
| `WHERE n.prop = val` | `WHERE json_extract(...) = val` | 属性过滤 |
| `MATCH (a)-[e]->(b)` | `JOIN edges ON a.id=e.source AND b.id=e.target` | 边遍历 |
| `RETURN n.name, n.kind` | `SELECT json_extract(...)` | 投影 |
| `LIMIT 10` | `LIMIT 10` | 分页 |

**用法：**

```python
engine = CypherEngine(graph_db_path)

# 原始查询
rows = engine.query("MATCH (f:Function) WHERE f.name='parse' RETURN f.name, f.file_path")

# 通过 graph_query 工具
tool_result = graph_query(query="MATCH (f)-[:CALLS]->(g) RETURN f.name, g.name", limit=20)
```

---

## 7. 错误处理

### 7.1 error_boundary 装饰器

每个工具都使用 `@error_boundary` 包装：

```python
@error_boundary("tool_name", timeout_ms=15000, max_retries=1)
async def execute(self, **kwargs) -> dict:
    ...
```

它保证：
1. **真实超时** 通过 `asyncio.wait_for(timeout_ms / 1000.0)`
2. **统一 JSON** 始终为：`{"status": "ok"|"error"|"timeout"|"warning", "message": "...", "detail": "...", "latency_ms": 123}`
3. **受控错误**（`ToolError`）→ 原样返回，不重试
4. **意外错误** → 记录完整回溯，返回 `"status": "error"`
5. **超时重试** — 可通过 `max_retries` 配置

### 7.2 ToolError 层次结构

```python
ToolError          # 基类：status, message, detail, recoverable
├── IndexNotReadyError  # 索引为空（警告，可恢复）
└── RateLimitError      # 速率限制超出（警告，可恢复）
```

---

## 8. 速率限制与弹性

### 8.1 SlidingWindowRateLimiter

```python
limiter = SlidingWindowRateLimiter()  # asyncio.Lock 用于线程安全

ok = await limiter.acquire("notify_change", max_per_sec=10.0)
if not ok:
    raise RateLimitError(detail="Too many notify_change calls")
```

### 8.2 DebounceBatch

替代每次文件更改时立即调用 `searcher.reindex()`：

```python
batch = DebounceBatch(callback=searcher.reindex, config=DebounceConfig(
    debounce_ms=500,    # 最后一个事件后 500ms
    max_batch_size=100, # 或在 100 个文件时立即刷新
    max_wait_ms=5000,   # 防止无限防抖
))
await batch.add("file.py")  # BM25 在 500ms 后（或在 100 个文件时）重建
```

### 8.3 CircuitBreaker

```python
cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="lm_studio")

result = await cb.call(
    lambda: embedder.embed_batch(texts),
    fallback={"status": "fallback", "message": "LM Studio unavailable"}
)
# 状态：CLOSED → OPEN（5 次失败）→ HALF_OPEN（30 秒后）→ CLOSED（成功时）
```

---

## 9. 数据流

```
Zed AI Agent
    │
    ▼
MCP 工具调用（例如 search_code("find indexer")）
    │
    ▼
error_boundary 装饰器
    ├── 超时检查（asyncio.wait_for）
    ├── 速率限制检查（SlidingWindowRateLimiter）
    └── 工具执行
            │
            ▼
    MCPTool.execute(**kwargs)
        │
        ├── self.require_index()  → 如果为空则 IndexNotReadyError
        ├── services.resolve(Searcher)
        ├── engine.hybrid_search(query)
        │       │
        │       ▼
        │   core/search/engine.py
        │       ├── BM25 搜索（内存 TF-IDF）
        │       ├── 向量搜索（LanceDB + ONNX E5-small，进程内）
        │       ├── FTS5 搜索（SQLite FTS5，trigram+porter）
        │       └── 3 路 RRF 融合 + MMR 多样性
        │
        └── return {"status": "ok", "results": [...]}
                │
                ▼
        error_boundary → {"status": "ok", ...latency_ms}
                │
                ▼
        Zed Chat（格式化的 JSON 响应）
```

---

## 10. Metadata Enrichment（v2.4.4+）

### 10.1 Chunk Metadata

每个存储在 LanceDB 中的块（chunk）包含 6 个元数据字段，用于确定性
过滤和多粒度检索：

| 字段 | 类型 | 示例 | 用途 |
|-------|------|---------|---------|
| `layer` | string | `"core"` | 架构层：core/mcp/utils/tests/... |
| `module_name` | string | `"core.parser"` | 从文件路径派生的逻辑模块名 |
| `hierarchy_level` | string | `"method"` | 层级：function/method/class/impl/lines |
| `is_public` | bool | `true` | 公开/私有（以 `_` 开头） |
| `symbol_type` | string | `"method_definition"` | AST 节点类型 |
| `parent_id` | string | md5 哈希 | 确定性父哈希 |

层检测 — 自动，按文件路径：

| 路径 | layer |
|------|-------|
| `src/core/*` | `core` |
| `src/mcp/tools/*` | `mcp_tools` |
| `src/mcp/*` | `mcp` |
| `src/utils/*` | `utils` |
| `tests/*` | `tests` |
| `docs/*` | `docs` |
| `.agents/*` | `agents` |
| `scripts/*` | `scripts` |
| `.github/*` | `ci` |
| 其他 | `root` |

### 10.2 扁平树层次结构（SproutRAG 风格）

`parent_id` — 确定性 md5 哈希：

- **对于方法：** `md5(file_path + "::" + class_name)` — 父级 = 类
- **对于函数：** `md5(file_path)` — 父级 = 模块
- **对于巨型函数部分：** `md5(file_path + "::" + symbol_name)` — 父级 = 函数

无需图数据库即可实现多粒度检索：
- 查找类的所有方法 → `get_chunks_by_parent_id("md5_hash")`
- 向上导航到模块 → 按 parent_id 聚合

### 10.3 search_code 中的层过滤

```python
# 仅核心层
search_code(query="DI container", filter_layer="core")

# 仅测试
search_code(query="test_parser", filter_layer="tests")

# 无过滤（所有层，与之前一样）
search_code(query="parser")
```

层过滤在 LanceDB 级别通过 `.where(prefilter=True)` 工作 — 向量搜索仅搜索指定层的块（chunk）。BM25 从元数据中按层进行后过滤。

---

## 10. Windows 特定处理

### 10.1 路径解析

`PROJECT_PATH` 可能包含 `$ZED_WORKTREE_ROOT` 字面字符串（Zed 在 Windows 上未解析环境变量）。
解决方案：`resolve_project_root()` 检查 7 种回退（fallback）策略：

1. 提供的参数
2. LSP→MCP 桥接器（bridge）（来自 LSP 的临时文件，后者知道 `root_uri`）
3. `PROJECT_PATH` 环境变量（如果不是 `$ZED` 则已解析）
4. 如果 `ext_root` 是 git 仓库
5. `ZED_WORKTREE_ROOT` 环境变量
6. CWD（来自 Zed `settings.json`）
7. `ext_root` 作为最终回退（fallback）

### 10.2 Git 子进程安全

```python
env["GIT_TERMINAL_PROMPT"] = "0"    # 无交互式提示
env["GIT_ASKPASS"] = "echo"         # 无凭据助手
env["GIT_PAGER"] = "cat"            # 无分页器
creationflags = subprocess.CREATE_NO_WINDOW  # 无控制台窗口
```

### 10.3 长路径支持

SafePathManager 对超过 260 个字符的路径使用 `to_win_long_path()`（在前面加上 `\\?\`）。

---

## 11. 多窗口注册表（v2.3+）

v2.3+ 支持 **同时在 Zed 中打开多个项目**。
以前 DI 持有一个单例 `Indexer` — 切换窗口时，状态会损坏
（一个 `file_guard`，一个 `db_path`，共享的 `SymbolIndex`）。

### 11.1 `ProjectIndexerRegistry`

`src/core/indexing/project_indexer_registry.py` — 线程安全的 `Indexer` 对象注册表：

```python
registry = ProjectIndexerRegistry(
    max_cached=5,                      # LRU 限制（5 个项目 = 1-2.5GB RAM）
    resource_monitor=get_global_resource_monitor(),  # 自适应节流
)

# 每个项目通过工厂懒创建：
def _create_indexer(p: Path) -> Indexer:
    return Indexer(
        db_path=_generate_unique_db_path(p),
        file_guard=FileGuard(p),
        symbol_index=SymbolIndex(),  # 隔离
        project_path=p, ...
    )

services.add_singleton(IndexerFactoryKey, _create_indexer)
indexer = registry.get_indexer(project_path, factory=_create_indexer)
```

**保证：**
- **隔离性：** 每个窗口获得自己的 `FileGuard`/`SymbolIndex`/`db_path`。
- **LRU：** 当第 6 个项目打开时，最旧的 `Indexer` 被驱逐。
- **压力驱逐：** 当 RAM > 1GB 或 CPU > 85% 时 — 在创建新的 `Indexer` **之前**强制驱逐（防止 OOM）。
- **清理：** `_safe_close()` 重置 LanceDB 连接 + `gc.collect()`（用于 Windows mmap 句柄）。

### 11.2 `ResourceMonitor`

`src/core/indexing/resource_monitor.py` — 仅使用标准库的监控（无 `psutil`）：

| 平台 | 方法 |
|-----------|-------|
| POSIX | `resource.getrusage(RUSAGE_SELF).ru_maxrss` |
| Windows | `psapi.GetProcessMemoryInfo` 通过 `ctypes` |
| CPU | `resource.getrusage` utime+stime 增量 / 挂钟时间 |

**阈值：**
- 软阈值：768MB / 75% CPU → 节流索引（文件间延迟 0.1s）
- 硬阈值：1024MB / 85% CPU → 压力驱逐 + 0.5-2s 延迟

```python
monitor = get_global_resource_monitor()
snap = monitor.sample()  # ResourceSnapshot (rss_mb, cpu_percent, threads)

if monitor.is_under_pressure():
    delay = monitor.suggest_throttle_delay_sec()
    time.sleep(delay)  # 在 Indexer.index_project 中文件之间
```

### 11.3 LSP 按工作区 DI

`src/lsp_main.py` 存储 **按工作区** 的 DI 容器：

```python
_services_per_workspace: dict[str, ServiceCollection] = {}

@server.feature("initialize")
async def on_initialize(ls, params):
    project_root = Path(urlparse(params.root_uri).path)
    ls._workspace_uri = params.root_uri
    ls._project_root = project_root
    init_components(project_root, workspace_uri=params.root_uri)
    # → 为一个窗口创建隔离的 DI 容器
```

LSP 处理程序（`did_open`/`did_change`/`did_save`/`did_close`/
`didChangeWatchedFiles`）接收 `ls._workspace_uri` 并通过注册表解析正确的 `Indexer`。

### 11.4 MCP `resolve_indexer_for_request`

`src/mcp/tools/base.py` — 按项目 Indexer 的单一入口点：

```python
def resolve_indexer_for_request(services, explicit_project_root=None):
    target = explicit_project_root or resolve_project_root() or DI_default
    registry = services.resolve(ProjectIndexerRegistry)
    factory = services.resolve(IndexerFactoryKey)
    return registry.get_indexer(target, factory=factory)

class MCPTool:
    def resolve_indexer(self, project_root=None):
        return resolve_indexer_for_request(self._services, project_root)
```

**所有 MCP 工具** 必须使用 `self.resolve_indexer(...)`
而不是 `self._services.resolve(Indexer)` — 后者不再有效
（Indexer 不是单例）。

### 11.5 HealthReport `_check_resources`

`src/core/code_health.py` — 新增方法：

```python
def _check_resources(self):
    summary = get_global_resource_monitor().get_summary()
    self.metrics["process_rss_mb"] = summary["rss_mb"]
    self.metrics["process_cpu_percent"] = summary["cpu_percent"]
    self.metrics["registry_cached_projects"] = ...
    self.metrics["registry_evictions"] = ...
    if summary["under_hard_pressure"]:
        self.issues.append({...})
```

---

## 12. 测试策略

```
tests/
├── test_error_handler.py     # 18 个测试 — ToolError, error_boundary
├── test_rate_limiter.py      # 21 个测试 — SlidingWindow, DebounceBatch, CircuitBreaker
├── test_di_container.py      # 13 个测试 — ServiceCollection, 15 services
├── test_resource_monitor.py  # 11 个测试 — ResourceMonitor + ProjectIndexerRegistry (v2.3+)
├── test_parser.py            # 4 个测试 — Tree-sitter 解析
├── test_execution_contract.py# 10 个测试 — verify_action
├── test_task_queue.py        # 6 个测试 — 后台任务队列
├── test_branch_aware_index.py# 8 个测试 — get_branch_info
├── test_symbol_index_call_graph.py  # 8 个测试 — 调用图
├── ...（还有 20 多个测试文件）
```

**总计：396 个测试。**

运行：
```bash
pytest tests/ -m "not integration and not benchmark"
```

---

## 快速参考

| 命令 | 描述 |
|---------|-------------|
| `python -m src.main` | 运行 MCP 服务器（STDIO） |
| `pytest tests/` | 运行所有测试 |
| `pytest tests/test_di_container.py -v` | 仅运行 DI 容器测试 |
| `python -c "from src.mcp.server import create_mcp_server; mcp = create_mcp_server()"` | 验证服务器加载 |

---

## 13. 架构不变规则

以下规则在任何新的 PR 中不得被违反。

```
1. 工具不直接访问 Registry。
2. 工具不直接读取 Bridge。
3. 工具仅通过 RuntimeCoordinator 工作。
4. RuntimeCoordinator 不了解 Search / Indexer / Memory。
5. ProjectContext 是不可变快照（不启动操作）。
6. 所有系统文件仅通过 SystemArtifacts 定义。
7. 索引器从不索引系统工件。
8. 任何项目路径都通过单一解析器（resolve_project_root）。
9. 所有 Intel 工具使用 ProjectContext（而非低级 API）。
10. 任何新的运行时组件必须具有单一职责。
11. 核心层没有 MCP 导入。
12. 工具不创建依赖 — 一切通过 DI。
13. server.py 仅注册 — 不包含业务逻辑。
```

**代码审查检查：** 每个 PR 必须回答问题
"此扩展属于哪个现有层？"。如果答案是"没有，我创建了一个
新的 Manager/Services/Provider" — 这是停下来重新考虑的理由。
