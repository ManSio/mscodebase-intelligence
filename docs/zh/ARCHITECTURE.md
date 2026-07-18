<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](../en/ARCHITECTURE.md) • [🇷🇺 Русский](../ru/ARCHITECTURE.md) • [🇨🇳 中文](ARCHITECTURE.md)

# MSCodeBase Intelligence — 架构指南

> **版本:** 3.2.0  
> **最后更新:** 2026-07-12  
> **架构:** 4层架构 + PropertyGraph + Data Flow Layer 带多窗口注册表

---

## 目录

1. [核心原则](#1-核心原则)
2. [分层架构](#2-分层架构)
3. [DI容器（ServiceCollection）](#3-di容器)
4. [工具层（41个基于类 + 14个intel + 3个诊断 = 共58个）](#4-工具层)
5. [错误处理](#5-错误处理)
6. [速率限制与弹性](#6-速率限制与弹性)
7. [数据流：请求 → 响应](#7-数据流)
8. [Windows特定事项](#8-windows特定事项)
9. [多窗口注册表（v2.3+）](#9-多窗口注册表v23)
10. [测试策略](#10-测试策略)

---

## 1. 核心原则

```
┌──────────────────────────────────────────────────────────────────┐
│              四层架构                                              │
│                                                                  │
│  第1层: main.py / lsp_main.py  (入口点，极简)                      │
│  第2层: mcp/server.py          (DI路由，工具注册)                   │
│  第3层: mcp/tools/*.py         (40个基于类的工具)                   │
│  第4层: core/*.py              (纯业务逻辑)                        │
└──────────────────────────────────────────────────────────────────┘
```

**关键规则:**
- **核心层没有MCP导入。** 它是带有业务逻辑的纯Python。
- **工具层永不创建依赖。** 所有依赖来自DI。
- **server.py仅负责注册** — 不含逻辑、格式化、try/except。
- **依赖向下流动：** 主程序 ← 服务器 ← 工具 ← 核心。

---

## 2. 分层架构

### 2.0 十层运行时架构（v2.4）

```
 第0层: Filesystem                  — 磁盘上有哪些文件？
 第1层: SystemArtifacts             — 这是系统路径吗？
 第2层: Bridge (LSP→MCP)           — LSP报告了哪个项目？
 第3层: Registry (IndexerRegistry)  — 哪个Indexer属于该项目？
 第4层: StateMachine (ProjectState) — 项目处于什么状态？
 第5层: RuntimeCoordinator          — 能否执行请求？
 第6层: ProjectContext              — 项目当前状况如何？
 第7层: Passport                    — 当前运行的是哪个进程？
 第8层: Intel Layer                 — 如何处理信息？
 第9层: MCP Tools / AI Agent        — 回复用户
```

**数据流:**
```
Filesystem → SystemArtifacts → Bridge → Registry → StateMachine
                                                          ↓
MCP Tools ← Intel Layer ← ProjectContext ← RuntimeCoordinator
```

**关键规则：** 工具不能直接访问 Registry、Bridge 或 Passport。
所有访问必须通过 `RuntimeCoordinator.can_execute()` + `ProjectContext.capture()`。

### 2.1 入口点

| 文件 | 协议 | 用途 |
|------|------|------|
| `src/main.py` | MCP STDIO | Zed Chat中的AI助手 |
| `src/lsp_main.py` | LSP STDIO | 通过Zed的didSave/didChange进行索引 |

两者使用相同的 `create_service_collection()` 工厂。

### 2.2 MCP服务器

`src/mcp/server.py` — **约220行**（重构前为3,100行）。

职责：
1. 解析项目根目录（`resolve_project_root()`）
2. 创建DI容器（`create_service_collection()`）
3. 注册16个core工具 + 14个intel工具 + 3个诊断工具 = 33个总计
4. 注册系统提示词（mscodebase-rules）
4. 注册系统提示词（mscodebase-rules）

**此处不包含业务逻辑。** 每个工具都从 `mcp/tools/` 导入。

### 2.3 工具层

`src/mcp/tools/*.py` — **12个文件，19个核心工具（Hub & Spoke：codebase + execute_script + 17个原生）。**

每个工具：
- 继承自 `MCPTool`（抽象基类）
- 通过构造函数接收依赖（构造函数注入）
- 有且只有一个入口点：`async def execute(**kwargs) -> dict`
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
        self.require_index()  # 检查索引是否就绪
        # ... 逻辑
```

### 2.4 核心层

`src/core/*.py` — **30个纯业务逻辑文件。**

关键模块：

| 模块 | 用途 | 依赖 |
|------|------|------|
| `di_container.py` | DI容器（15个服务） | — |
| `error_handler.py` | ToolError + error_boundary | — |
| `rate_limiter.py` | DebounceBatch + CircuitBreaker | — |
| `indexer.py` | LanceDB向量存储 | embedder, file_guard, parser |
| `searcher.py` | 混合搜索（BM25 + Dense + RRF） | indexer, embedder |
| `symbol_index.py` | 调用图（BFS, PageRank） | parser |
| `graph.py` **(新增 v3.0)** | **PropertyGraph — SQLite 属性图** | — |
| `graph_adapter.py` **(新增 v3.0)** | **SymbolIndexAdapter 包装 PropertyGraph** | graph, symbol_index |
| `cypher_engine.py` **(新增 v3.0)** | **Cypher→SQL 引擎** | graph |
| `route_extractor.py` **(新增 v3.0)** | **HTTP 路由检测** | graph |
| `multi_signal_scorer.py` **(新增 v3.0)** | **多信号搜索评分（4个信号）** | graph |
| `dataflow_experiment.py` **(新增 v3.2)** | **ASSIGNED_FROM, IMPORTS 基准测试** | parser |
| `intelligence_layer.py` | 14个intel_*工具 | indexer, searcher, symbol_index |
| `llama_runner.py` | llama-server.exe生命周期管理器 | download, launch, stop |
| `remote_embedder.py` | LM Studio / llama.cpp / Ollama / ONNX | config |
| `parser.py` | Tree-sitter AST | — |
| `file_guard.py` | .gitignore + 扩展名过滤器 | config |

### 2.5 Data Flow Layer (v3.2.0)

```
┌──────────────────────────────────────────────────────────────────┐
│  Data Flow Layer                                                 │
│                                                                  │
│  1. Unified Walker — _walk_file()                                │
│     一次 Tree-sitter 解析 + 一次遍历 → 调用 + 赋值                │
│     Parse cache: 同一文件重复调用时跳过解析                       │
│                                                                  │
│  2. Conditional Flow                                             │
│     ASSIGNED_FROM, IMPORTS 边包含可选的 condition_path 属性                │
│     → ["if_statement", "for_statement", "try", "except"]         │
│     追踪 if/for/while/try/except 嵌套层级                         │
│                                                                  │
│  3. 仅限函数内部                                                 │
│     追踪仅在函数体内部工作                                        │
│     跨函数数据流不追踪（已知限制）                                 │
│                                                                  │
│  4. 目前仅 Python                                                │
│     Rust/TS 解析器已存在，但赋值节点类型不同                      │
│                                                                  │
│  5. src/core 中 30 个文件                                        │
└──────────────────────────────────────────────────────────────────┘
```

### 2.6 提供者优先级

MCP服务器自动检测最佳可用的嵌入提供者：

1. **ONNX/OpenVINO INT8（进程内）** — 默认且主要，无需外部服务器（E5-base，768维，~350 ch/s）
2. **llama.cpp GGUF（GPU）** — 可选加速，通过 `install.py` 自动安装
3. **LM Studio** — 可选 fallback，需要外部服务器
4. **Ollama / remote ONNX** — 自定义设置

优先级在启动时评估。ONNX/OpenVINO 相比 LM Studio 提供约 5.3 倍的 RAM 减少（~265 MB 对比 ~1200 MB）。

---

## 3. DI容器

### 3.1 ServiceCollection

```python
# src/core/di_container.py

services = ServiceCollection()

# 注册单例：
services.add_singleton(Indexer, indexer_instance)

# 注册懒加载工厂：
services.add_factory(Searcher, lambda s: Searcher(s.resolve(Indexer), ...))

# 解析：
indexer = services.resolve(Indexer)  # 每次返回同一实例
```

### 3.2 已注册服务（15个）

| # | 服务 | 类型 | 创建方式 |
|---|------|------|----------|
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
| 12 | ResourceMonitorKey | 单例 | `ResourceMonitor` (共享) |
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
        # Search (3)
        SearchCodeTool, GetSymbolInfoTool, ImpactAnalysisTool,
        # Hub: codebase (write/index/git/notify — 通过action复用)
        CodebaseTool,
        # Spoke: E2B沙箱
        ExecuteScriptTool,
        # Analysis (5)
        StructuralSearchTool, GetRepoMapTool, GetRepoRankTool,
        ScanChangesTool, GenerateChunkSummariesTool,
        # Graph (3 — 第二阶段: graph_query复用cypher + related + flow)
        CrossRepoSearchTool, CrossProjectDepsTool, GraphQueryTool,
        # Investigation (3)
        GetBugCorrelationTool, GetHotspotsTool, FindSimilarBugsTool,
        # Lifecycle (3)
        SubmitBackgroundTaskTool, GetTaskStatusTool, VerifyActionTool,
    ]
    # +14 个intel工具 + 3 个诊断工具
    # 总计: 36 个注册 (19 core + 14 intel + 3 diag)
```

**可见性过滤器:** 默认 ~16 个工具可见。设置 `MSCODEBASE_MCP_TOOLS=""` 显示全部 36 个。

### 4.2 按组分组的全部工具

| 组 | 文件 | 工具 |
|-------|------|-------|
| **搜索**（3） | `search_tools.py` | search_code, get_symbol_info, impact_analysis |
| **Hub: codebase**（1） | `codebase_tool.py` | codebase(action={rename,move,delete,replace,insert,notify,index,git,branch,...}) |
| **Spoke: E2B**（1） | `codebase_tool.py` | execute_script(code) |
| **分析**（5） | `analysis_tools.py` | structural_search, get_repo_map, get_repo_rank, scan_changes, generate_chunk_summaries |
| **图**（3） | `graph_tools.py` | cross_repo_search, cross_project_deps, graph_query(action={query,cypher,related,flow}) |
| **调查**（3） | `investigation_tools.py` | get_bug_correlation, get_hotspots, find_similar_bugs |
| **生命周期**（3） | `lifecycle_tools.py` | submit_background_task, get_task_status, verify_action |
| **智能层**（14） | `intelligence_layer.py` | intel_get_runtime_status, intel_get_job_status, intel_code_topology, intel_log_incident, intel_get_project_memory, intel_add_memory_node, intel_get_hotspots, intel_analyze_incident, intel_predict_root_cause, intel_trigger_reindex, intel_get_project_context, intel_explain_project_state, intel_get_telemetry, intel_tool_health |
| **Diagnostic**（3） | `server_tools.py` 内联 | debug_runtime_passport, get_runtime_counters, intel_execution_timeline |

> **总计:** 36 个注册 (19 core + 14 intel + 3 diag)。
> **默认可见:** ~16。显示全部: `MSCODEBASE_MCP_TOOLS=""`。

## 5. 错误处理

### 5.1 error_boundary 装饰器

每个工具都用 `@error_boundary` 包裹：

```python
@error_boundary("tool_name", timeout_ms=15000, max_retries=1)
async def execute(self, **kwargs) -> dict:
    ...
```

它保证：
1. **真实超时** — 通过 `asyncio.wait_for(timeout_ms / 1000.0)`
2. **统一JSON格式** — 始终返回：`{"status": "ok"|"error"|"timeout"|"warning", "message": "...", "detail": "...", "latency_ms": 123}`
3. **受控错误**（`ToolError`）→ 直接返回，不重试
4. **意外错误** → 记录完整回溯，返回 `"status": "error"`
5. **超时重试** — 可通过 `max_retries` 配置

### 5.2 ToolError 层次结构

```python
ToolError          # 基础：status, message, detail, recoverable
├── IndexNotReadyError  # 索引为空（warning, recoverable）
└── RateLimitError      # 超出速率限制（warning, recoverable）
```

---

## 6. 速率限制与弹性

### 6.1 SlidingWindowRateLimiter

```python
limiter = SlidingWindowRateLimiter()  # asyncio.Lock 保证线程安全

ok = await limiter.acquire("notify_change", max_per_sec=10.0)
if not ok:
    raise RateLimitError(detail="Too many notify_change calls")
```

### 6.2 DebounceBatch

替代每次文件变更时立即调用 `searcher.reindex()`：

```python
batch = DebounceBatch(callback=searcher.reindex, config=DebounceConfig(
    debounce_ms=500,    # 最后一个事件后500ms
    max_batch_size=100, # 或积累100个文件时立即触发
    max_wait_ms=5000,   # 防止无限防抖
))
await batch.add("file.py")  # BM25将在500ms后重建（或积累100个文件时）
```

### 6.3 CircuitBreaker

```python
cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="lm_studio")

result = await cb.call(
    lambda: embedder.embed_batch(texts),
    fallback={"status": "fallback", "message": "LM Studio unavailable"}
)
# 状态：CLOSED → OPEN（5次失败）→ HALF_OPEN（30秒后）→ CLOSED（成功）
```

---

## 7. 数据流

```
Zed AI Agent
    │
    ▼
MCP Tool Call (e.g., search_code("find indexer"))
    │
    ▼
error_boundary decorator
    ├── 超时检查 (asyncio.wait_for)
    ├── 速率限制检查 (SlidingWindowRateLimiter)
    └── 工具执行
            │
            ▼
    MCPTool.execute(**kwargs)
        │
        ├── self.require_index()  → 如果为空则抛出 IndexNotReadyError
        ├── services.resolve(Searcher)
        ├── searcher.search(query)
        │       │
        │       ▼
        │   core/searcher.py
        │       ├── BM25搜索（内存中TF-IDF）
        │       ├── 向量搜索（LanceDB + ONNX E5-base，进程内）
        │       └── RRF融合 + 重排序
        │
        └── return {"status": "ok", "results": [...]}
                │
                ▼
        error_boundary → {"status": "ok", ...latency_ms}
                │
                ▼
        Zed Chat（格式化JSON响应）
    ```

    ---

    ## 8. 元数据增强（v2.4.4+）

    ### 8.1 语义指南针（MCompassRAG风格）

    每个LanceDB中的块包含6个元数据字段，用于确定性
    过滤和多粒度检索：

    | 字段 | 类型 | 示例 | 用途 |
    |------|------|------|------|
    | `layer` | string | `"core"` | 架构层：core/mcp/utils/tests/... |
    | `module_name` | string | `"core.parser"` | 从文件路径推导的模块逻辑名 |
    | `hierarchy_level` | string | `"method"` | 层次：function/method/class/impl/lines |
    | `is_public` | bool | `true` | 公开/私有（`_`前缀） |
    | `symbol_type` | string | `"method_definition"` | AST节点类型 |
    | `parent_id` | string | md5哈希 | 父元素的确定性哈希 |

    层检测 — 自动根据文件路径确定：

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

    ### 8.2 扁平树层次结构（SproutRAG风格）

    `parent_id` — 确定性md5哈希：

    - **对于方法：** `md5(file_path + "::" + class_name)` — parent = 类
    - **对于函数：** `md5(file_path)` — parent = 模块
    - **对于巨型函数的一部分：** `md5(file_path + "::" + symbol_name)` — parent = 函数

    允许无需图数据库即可进行多粒度检索：
    - 查找类的所有函数 → `get_chunks_by_parent_id("md5_hash")`
    - 上溯到模块 → 按parent_id聚合

    ### 8.3 search_code 中的层过滤

    ```python
    # 仅 core 层
    search_code(query="DI container", filter_layer="core")

    # 仅 tests
    search_code(query="test_parser", filter_layer="tests")

    # 无过滤器（所有层，和之前一样）
    search_code(query="parser")
    ```

    过滤在LanceDB层面使用 `.where(prefilter=True)` — 向量
    搜索只扫描目标层的块。BM25从metadata中按layer进行后过滤。

    ---

    ## 9. Windows特定事项

### 8.1 路径解析

`PROJECT_PATH` 可能包含 `$ZED_WORKTREE_ROOT` 字面字符串（Zed在Windows上未解析环境变量）。
解决方案：`resolve_project_root()` 检查7种回退策略：

1. 提供的参数
2. LSP→MCP桥接（来自知道 `root_uri` 的LSP的临时文件）
3. `PROJECT_PATH` 环境变量（如果不是 `$ZED` 则解析）
4. `ext_root` — 如果它是git仓库
5. `ZED_WORKTREE_ROOT` 环境变量
6. CWD（来自Zed `settings.json`）
7. `ext_root` 作为最终回退

### 8.2 Git子进程安全

```python
env["GIT_TERMINAL_PROMPT"] = "0"    # 无交互式提示
env["GIT_ASKPASS"] = "echo"         # 无凭据助手
env["GIT_PAGER"] = "cat"            # 无分页器
creationflags = subprocess.CREATE_NO_WINDOW  # 无控制台窗口
```

### 8.3 长路径支持

SafePathManager 对超过260个字符的路径使用 `to_win_long_path()`（添加 `\\?\` 前缀）。

---

## 9. 多窗口注册表（v2.3+）

v2.3+ 支持**在Zed中同时打开多个项目**。
以前DI持有单例 `Indexer` — 切换窗口时状态会损坏
（一个 `file_guard`，一个 `db_path`，共享的 `SymbolIndex`）。

### 9.1 `ProjectIndexerRegistry`

`src/core/project_indexer_registry.py` — 线程安全的 `Indexer` 注册表：

```python
registry = ProjectIndexerRegistry(
    max_cached=5,                      # LRU限制（5个项目 = 1-2.5GB RAM）
    resource_monitor=get_global_resource_monitor(),  # 自适应节流
)

# 按项目的懒加载工厂：
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

**保证:**
- **隔离性：** 每个窗口获得自己的 `FileGuard`/`SymbolIndex`/`db_path`。
- **LRU：** 打开第6个项目时，最旧的 `Indexer` 被淘汰。
- **压力驱逐：** RAM > 1GB 或 CPU > 85% 时 — 在创建新 `Indexer` **之前**
  强制驱逐（防止OOM）。
- **清理：** `_safe_close()` 清空 LanceDB 连接 + `gc.collect()`
  （用于Windows mmap句柄）。

### 9.2 `ResourceMonitor`

`src/core/resource_monitor.py` — 仅使用stdlib的监控（无 `psutil`）：

| 平台 | 方法 |
|------|------|
| POSIX | `resource.getrusage(RUSAGE_SELF).ru_maxrss` |
| Windows | `psapi.GetProcessMemoryInfo` 通过 `ctypes` |
| CPU | `resource.getrusage` utime+stime 增量 / 挂钟时间 |

**阈值:**
- 软阈值：768MB / 75% CPU → 节流索引（文件间延迟0.1s）
- 硬阈值：1024MB / 85% CPU → 强制驱逐 + 0.5-2s 延迟

```python
monitor = get_global_resource_monitor()
snap = monitor.sample()  # ResourceSnapshot (rss_mb, cpu_percent, threads)

if monitor.is_under_pressure():
    delay = monitor.suggest_throttle_delay_sec()
    time.sleep(delay)  # 在 Indexer.index_project 的文件之间
```

### 9.3 LSP 按工作区 DI

`src/lsp_main.py` 存储**按工作区**的DI容器：

```python
_services_per_workspace: dict[str, ServiceCollection] = {}

@server.feature("initialize")
async def on_initialize(ls, params):
    project_root = Path(urlparse(params.root_uri).path)
    ls._workspace_uri = params.root_uri
    ls._project_root = project_root
    init_components(project_root, workspace_uri=params.root_uri)
    # → 为窗口创建隔离的DI容器
```

LSP处理器（`did_open`/`did_change`/`did_save`/`did_close`/
`didChangeWatchedFiles`）获取 `ls._workspace_uri` 并通过注册表
解析正确的 `Indexer`。

### 9.4 MCP `resolve_indexer_for_request`

`src/mcp/tools/base.py` — 获取按项目 Indexer 的单一入口：

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

**所有MCP工具** 应使用 `self.resolve_indexer(...)`
而不是 `self._services.resolve(Indexer)` — 后者不再有效
（Indexer不是单例）。

### 9.5 HealthReport `_check_resources`

`src/core/health_report.py` — 添加了方法：

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

## 10. 测试策略

```
tests/
├── test_error_handler.py     # 18个测试 — ToolError, error_boundary
├── test_rate_limiter.py      # 21个测试 — SlidingWindow, DebounceBatch, CircuitBreaker
├── test_di_container.py      # 13个测试 — ServiceCollection, 15个服务
├── test_resource_monitor.py  # 11个测试 — ResourceMonitor + ProjectIndexerRegistry (v2.3+)
├── test_parser.py            # 4个测试 — Tree-sitter解析
├── test_execution_contract.py# 10个测试 — verify_action
├── test_task_queue.py        # 6个测试 — 后台任务队列
├── test_branch_aware_index.py# 8个测试 — get_branch_info
├── test_symbol_index_call_graph.py  # 8个测试 — 调用图
├── ...（另外20个测试文件）
```

**总计：396个测试。**

运行：
```bash
pytest tests/ -m "not integration and not benchmark"
```

---

## 快速参考

| 命令 | 描述 |
|------|------|
| `python -m src.main` | 运行MCP服务器（STDIO） |
| `pytest tests/` | 运行所有测试 |
| `pytest tests/test_di_container.py -v` | 仅运行DI容器测试 |
| `python -c "from src.mcp.server import create_mcp_server; mcp = create_mcp_server()"` | 验证服务器加载 |

---

## 11. 架构不变规则

这些规则在任何新PR中**不得**被违反。

```
1. 工具不能直接访问 Registry。
2. 工具不能直接读取 Bridge。
3. 工具只能通过 RuntimeCoordinator 工作。
4. RuntimeCoordinator 不知道 Search / Indexer / Memory。
5. ProjectContext 是不可变快照（不启动操作）。
6. 所有系统文件仅通过 SystemArtifacts 确定。
7. 索引器从不索引系统工件。
8. 任何项目路径都通过统一的 resolver（resolve_project_root）。
9. 所有 Intel 工具使用 ProjectContext（而非低级API）。
10. 任何新的运行时组件必须只有一个职责。
11. 核心层没有 MCP 导入。
12. 工具不创建依赖 — 所有依赖通过 DI。
13. server.py 负责注册 — 不包含业务逻辑。
```

**代码审查检查点：** 任何PR必须回答「它扩展了哪个现有层？」。
如果答案是「没有，我创建了新的 Manager/Services/Provider」— 这是需要停下来思考的信号。
