<img src="../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

# MSCodeBase Intelligence — 架构指南

[🇬🇧 English](architecture.md) • [🇷🇺 Русский](architecture.ru.md) • [🇨🇳 中文](architecture.zh.md)

> **版本：** 2.4.4  
> **最后更新：** 2026-07-05  
> **架构：** 带 DI 容器 + 多窗口注册表的整洁架构

---

## 目录

1. [核心原则](#1-核心原则)
2. [分层架构](#2-分层架构)
3. [DI 容器（ServiceCollection）](#3-di-容器)
4. [工具层（33 个基于类 + 10 个 intel = 共 43 个）](#4-工具层)
5. [错误处理](#5-错误处理)
6. [速率限制与弹性](#6-速率限制与弹性)
7. [数据流：请求 → 响应](#7-数据流)
8. [Windows 特性](#8-windows-特性)
9. [多窗口注册表（v2.3+）](#9-多窗口注册表-v23)
10. [测试策略](#10-测试策略)

---

## 1. 核心原则

```
┌──────────────────────────────────────────────────────────────────┐
│              整洁架构的四个层次                                    │
│                                                                  │
│  第 1 层：main.py / lsp_main.py  （入口点，最小化）                │
│  第 2 层：mcp/server.py          （DI 路由，工具注册）              │
│  第 3 层：mcp/tools/*.py         （33 个基于类的工具）              │
│  第 4 层：core/*.py              （纯业务逻辑）                    │
└──────────────────────────────────────────────────────────────────┘
```

**关键规则：**
- **核心层没有 MCP 导入。** 它是带有业务逻辑的纯 Python。
- **工具层绝不创建依赖。** 所有内容来自 DI。
- **server.py 仅注册** — 无逻辑、无格式化、无 try/except。
- **依赖向下流动：** Main ← Server ← Tools ← Core。

---

## 2. 分层架构

### 2.0 十层运行时架构（v2.4）

```
 第 0 层：文件系统                  — 磁盘上有哪些文件？
 第 1 层：SystemArtifacts           — 这是系统路径吗？
 第 2 层：桥接（LSP→MCP）           — LSP 报告了哪个项目？
 第 3 层：注册表（IndexerRegistry）  — 哪个 Indexer 属于此项目？
 第 4 层：状态机（ProjectState）     — 项目处于什么状态？
 第 5 层：RuntimeCoordinator        — 可以执行请求吗？
 第 6 层：ProjectContext            — 项目当前看起来如何？
 第 7 层：护照                      — 当前运行的是哪个进程？
 第 8 层：Intel 层                  — 如何处理这些信息？
 第 9 层：MCP 工具 / AI 代理        — 返回给用户
```

**数据流：**
```
文件系统 → SystemArtifacts → 桥接 → 注册表 → 状态机
                                                          ↓
MCP 工具 ← Intel 层 ← ProjectContext ← RuntimeCoordinator
```

**关键规则：** 工具**不**直接访问 Registry、Bridge 或 Passport。
全部通过 `RuntimeCoordinator.can_execute()` + `ProjectContext.capture()`。

### 2.1 入口点

| 文件 | 协议 | 用途 |
|------|----------|---------|
| `src/main.py` | MCP STDIO | Zed 聊天中的 AI 助手 |
| `src/lsp_main.py` | LSP STDIO | 通过来自 Zed 的 didSave/didChange 进行索引 |

两者使用相同的 `create_service_collection()` 工厂。

### 2.2 MCP 服务器

`src/mcp/server.py` — **约 220 行**（重构前为 3,100 行）。

职责：
1. 解析项目根目录（`resolve_project_root()`）
2. 创建 DI 容器（`create_service_collection()`）
3. 注册 33 个工具 + 10 个 intel_* 工具
4. 注册系统提示（mscodebase-rules）

**这里没有业务逻辑。** 每个工具都是从 `mcp/tools/` 导入的。

### 2.3 工具层

`src/mcp/tools/*.py` — **10 个文件，33 个工具。**

每个工具：
- 继承自 `MCPTool`（ABC）
- 通过构造函数接收依赖（构造函数注入）
- 只有一个入口点：`async def execute(**kwargs) -> dict`
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
        # ... 逻辑
```

### 2.4 核心层

`src/core/*.py` — **23 个纯业务逻辑文件。**

关键模块：

| 模块 | 用途 | 依赖 |
|--------|---------|------------|
| `di_container.py` | DI 容器（15 个服务） | — |
| `error_handler.py` | ToolError + error_boundary | — |
| `rate_limiter.py` | DebounceBatch + CircuitBreaker | — |
| `indexer.py` | LanceDB 向量存储 | embedder, file_guard, parser |
| `searcher.py` | 混合搜索（BM25 + Dense + RRF） | indexer, embedder |
| `symbol_index.py` | 调用图（BFS, PageRank） | parser |
| `intelligence_layer.py` | 10 个 intel_* 工具 | indexer, searcher, symbol_index |
| `remote_embedder.py` | LM Studio / Ollama / ONNX | config |
| `parser.py` | Tree-sitter AST | — |
| `file_guard.py` | .gitignore + 扩展名过滤 | config |

---

## 3. DI 容器

### 3.1 ServiceCollection

```python
# src/core/di_container.py

services = ServiceCollection()

# 注册单例：
services.add_singleton(Indexer, indexer_instance)

# 注册惰性工厂：
services.add_factory(Searcher, lambda s: Searcher(s.resolve(Indexer), ...))

# 解析：
indexer = services.resolve(Indexer)  # 每次都返回相同实例
```

### 3.2 注册的服务（15 个）

| # | 服务 | 类型 | 创建方式 |
|---|---------|------|------------|
| 1 | Path (project_root) | singleton | explicit |
| 2 | Path (db_path) | singleton | `_generate_unique_db_path()` |
| 3 | CodeParser | singleton | `CodeParser()` |
| 4 | FileGuard | singleton | `FileGuard(project_root)` |
| 5 | RemoteEmbedder | singleton | `RemoteEmbedder()` |
| 6 | SymbolIndex | singleton | `SymbolIndex()` |
| 7 | SlidingWindowRateLimiter | singleton | `SlidingWindowRateLimiter()` |
| 8 | LmStudioCircuitBreaker | singleton | `CircuitBreaker(name="lm_studio")` |
| 9 | Indexer | singleton | `Indexer(db_path, embedder, ...)` |
| 10 | Searcher | singleton | `Searcher(indexer, embedder)` |
| 11 | DebounceBatch | singleton | `DebounceBatch(callback=searcher.reindex)` |
| 12 | ProjectRegistry | singleton | `ProjectRegistry()` |
| 13 | MultiProjectSearcher | singleton | `MultiProjectSearcher(embedder, registry)` |

---

## 4. 工具层

### 4.1 工具注册

在 `src/mcp/server.py` 中：

```python
def _register_all_tools(mcp, services):
    tool_classes = [
        SearchCodeTool, GetSymbolInfoTool,
        NotifyChangeTool, IndexProjectDirTool,
        GetBranchInfoTool, GetIndexStatusTool,
        # ... 共 33 个
    ]

    for tool_cls in tool_classes:
        instance = tool_cls(services)
        mcp.tool(name=instance.name)(instance.execute)
```

### 4.2 按组划分的所有工具

| 组 | 文件 | 工具 |
|-------|------|-------|
| **搜索**（3） | `search_tools.py` | search_code, get_symbol_info, impact_analysis |
| **索引**（3） | `indexing_tools.py` | notify_change, index_project_dir, index_health |
| **Git**（3） | `git_tools.py` | get_branch_info, get_commit_history, get_file_history |
| **系统**（9） | `system_tools.py` | get_index_status, get_index_progress, get_index_timeline, watcher_status, get_logs, get_health_report, predict_eta, run_health_check, read_live_file |
| **分析**（5） | `analysis_tools.py` | structural_search, get_repo_map, get_repo_rank, scan_changes, generate_chunk_summaries |
| **图**（4） | `graph_tools.py` | cross_repo_search, cross_project_deps, graph_query, get_related_files |
| **调查**（3） | `investigation_tools.py` | get_bug_correlation, get_hotspots, find_similar_bugs |
| **生命周期**（3） | `lifecycle_tools.py` | submit_background_task, get_task_status, verify_action |
| **智能**（10） | `intelligence_layer.py` | intel_get_runtime_status, intel_get_job_status, intel_code_topology, intel_log_incident, intel_get_project_memory, intel_add_memory_node, intel_get_hotspots, intel_analyze_incident, intel_predict_root_cause, intel_trigger_reindex |

---

## 5. 错误处理

### 5.1 error_boundary 装饰器

每个工具都用 `@error_boundary` 包装：

```python
@error_boundary("tool_name", timeout_ms=15000, max_retries=1)
async def execute(self, **kwargs) -> dict:
    ...
```

它保证：
1. 通过 `asyncio.wait_for(timeout_ms / 1000.0)` **真正的超时**
2. **统一的 JSON** 始终为：`{"status": "ok"|"error"|"timeout"|"warning", "message": "...", "detail": "...", "latency_ms": 123}`
3. **受控错误**（`ToolError`）→ 原样返回，不重试
4. **意外错误** → 记录完整追踪，返回 `"status": "error"`
5. **超时重试** — 可通过 `max_retries` 配置

### 5.2 ToolError 层次结构

```python
ToolError          # 基础：status, message, detail, recoverable
├── IndexNotReadyError  # 索引为空（warning, recoverable）
└── RateLimitError      # 超过速率限制（warning, recoverable）
```

---

## 6. 速率限制与弹性

### 6.1 SlidingWindowRateLimiter

```python
limiter = SlidingWindowRateLimiter()  # asyncio.Lock 用于线程安全

ok = await limiter.acquire("notify_change", max_per_sec=10.0)
if not ok:
    raise RateLimitError(detail="Too many notify_change calls")
```

### 6.2 DebounceBatch

替代每次文件更改时立即调用 `searcher.reindex()`：

```python
batch = DebounceBatch(callback=searcher.reindex, config=DebounceConfig(
    debounce_ms=500,    # 最后一个事件后 500ms
    max_batch_size=100, # 或 100 个文件时 — 立即刷新
    max_wait_ms=5000,   # 防止无限去抖
))
await batch.add("file.py")  # BM25 将在 500ms 后重建（或 100 个文件时）
```

### 6.3 CircuitBreaker

```python
cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="lm_studio")

result = await cb.call(
    lambda: embedder.embed_batch(texts),
    fallback={"status": "fallback", "message": "LM Studio unavailable"}
)
# 状态：CLOSED → OPEN（5 次失败）→ HALF_OPEN（30 秒后）→ CLOSED（成功）
```

---

## 7. 数据流

```
Zed AI 代理
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
        ├── searcher.search(query)
        │       │
        │       ▼
        │   core/searcher.py
        │       ├── BM25 搜索（内存 TF-IDF）
        │       ├── 向量搜索（LanceDB + LM Studio）
        │       └── RRF 融合 + 重排序
        │
        └── return {"status": "ok", "results": [...]}
                │
                ▼
        error_boundary → {"status": "ok", ...latency_ms}
                │
                ▼
        Zed 聊天（格式化的 JSON 响应）
    ```

    ---

    ## 8. 元数据丰富（v2.4.4+）

    ### 8.1 语义指南针（MCompassRAG 风格）

    LanceDB 中的每个块包含 6 个元数据字段，用于确定性
    过滤和多粒度检索：

    | 字段 | 类型 | 示例 | 用途 |
    |------|-----|--------|------------|
    | `layer` | string | `"core"` | 架构层：core/mcp/utils/tests/... |
    | `module_name` | string | `"core.parser"` | 从文件路径派生的逻辑模块名称 |
    | `hierarchy_level` | string | `"method"` | 级别：function/method/class/impl/lines |
    | `is_public` | bool | `true` | 公开/私有（`_` 前缀） |
    | `symbol_type` | string | `"method_definition"` | AST 节点类型 |
    | `parent_id` | string | md5-哈希 | 父元素的确定性哈希 |

    层检测 — 自动，根据文件路径：

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

    ### 8.2 扁平树层次结构（SproutRAG 风格）

    `parent_id` — 确定性 md5-哈希：

    - **对于方法：** `md5(file_path + "::" + class_name)` — parent = 类
    - **对于函数：** `md5(file_path)` — parent = 模块
    - **对于巨型函数的一部分：** `md5(file_path + "::" + symbol_name)` — parent = 函数

    无需图数据库即可实现多粒度检索：
    - 查找类的所有函数 → `get_chunks_by_parent_id("md5_hash")`
    - 上升到模块 → 按 parent_id 聚合

    ### 8.3 search_code 中的层过滤

    ```python
    # 仅 core 层
    search_code(query="DI container", filter_layer="core")

    # 仅 tests
    search_code(query="test_parser", filter_layer="tests")

    # 无过滤（所有层，与之前一样）
    search_code(query="parser")
    ```

    过滤在 LanceDB 级别通过 `.where(prefilter=True)` 工作 — 向量
    搜索仅针对所需层的块进行。BM25 根据元数据中的 layer 进行后过滤。

    ---

    ## 9. Windows 特性

### 8.1 路径解析

`PROJECT_PATH` 可能包含文字字符串 `$ZED_WORKTREE_ROOT`（环境变量未被 Zed 在 Windows 上解析）。
解决方案：`resolve_project_root()` 检查 7 种回退策略：

1. 提供的参数
2. LSP→MCP 桥接（来自 LSP 的临时文件，它知道 `root_uri`）
3. `PROJECT_PATH` 环境变量（如果不是 `$ZED` 则解析）
4. 如果是 git 仓库则使用 `ext_root`
5. `ZED_WORKTREE_ROOT` 环境变量
6. CWD（来自 Zed `settings.json`）
7. `ext_root` 作为最终回退

### 8.2 Git 子进程安全

```python
env["GIT_TERMINAL_PROMPT"] = "0"    # 无交互提示
env["GIT_ASKPASS"] = "echo"         # 无凭据助手
env["GIT_PAGER"] = "cat"            # 无分页器
creationflags = subprocess.CREATE_NO_WINDOW  # 无控制台窗口
```

### 8.3 长路径支持

SafePathManager 使用 `to_win_long_path()`（添加 `\\?\` 前缀）处理超过 260 个字符的路径。

---

## 9. 多窗口注册表（v2.3+）

v2.3+ 支持 **Zed 中同时打开多个项目**。
以前 DI 存储了单例 `Indexer` — 切换窗口时状态会损坏
（一个 `file_guard`、一个 `db_path`、共享的 `SymbolIndex`）。

### 9.1 `ProjectIndexerRegistry`

`src/core/project_indexer_registry.py` — 线程安全的 `Indexer` 注册表：

```python
registry = ProjectIndexerRegistry(
    max_cached=5,                      # LRU 限制（5 个项目 = 1-2.5GB RAM）
    resource_monitor=get_global_resource_monitor(),  # 自适应节流
)

# 通过工厂按项目惰性创建：
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
- **隔离：** 每个窗口获得自己的 `FileGuard`/`SymbolIndex`/`db_path`。
- **LRU：** 打开第 6 个项目时，最旧的 `Indexer` 被淘汰。
- **压力淘汰：** 当 RAM > 1GB 或 CPU > 85% 时 — 在创建新 `Indexer` **之前**强制淘汰（防止 OOM）。
- **清理：** `_safe_close()` 清空 LanceDB 连接 + `gc.collect()`（针对 Windows mmap 句柄）。

### 9.2 `ResourceMonitor`

`src/core/resource_monitor.py` — 仅 stdlib 的监控（无需 `psutil`）：

| 平台 | 方法 |
|-----------|-------|
| POSIX | `resource.getrusage(RUSAGE_SELF).ru_maxrss` |
| Windows | 通过 `ctypes` 的 `psapi.GetProcessMemoryInfo` |
| CPU | `resource.getrusage` utime+stime delta / wall-clock |

**阈值：**
- 软：768MB / 75% CPU → 节流索引（文件间 0.1s 延迟）
- 硬：1024MB / 85% CPU → 压力淘汰 + 0.5-2s 延迟

```python
monitor = get_global_resource_monitor()
snap = monitor.sample()  # ResourceSnapshot（rss_mb, cpu_percent, threads）

if monitor.is_under_pressure():
    delay = monitor.suggest_throttle_delay_sec()
    time.sleep(delay)  # 在 Indexer.index_project 中文件之间
```

### 9.3 LSP 每个工作区 DI

`src/lsp_main.py` 存储**每个工作区**的 DI 容器：

```python
_services_per_workspace: dict[str, ServiceCollection] = {}

@server.feature("initialize")
async def on_initialize(ls, params):
    project_root = Path(urlparse(params.root_uri).path)
    ls._workspace_uri = params.root_uri
    ls._project_root = project_root
    init_components(project_root, workspace_uri=params.root_uri)
    # → 为窗口创建隔离的 DI 容器
```

LSP 处理器（`did_open`/`did_change`/`did_save`/`did_close`/
`didChangeWatchedFiles`）获取 `ls._workspace_uri` 并通过 registry 解析
正确的 `Indexer`。

### 9.4 MCP `resolve_indexer_for_request`

`src/mcp/tools/base.py` — 获取按项目 Indexer 的统一入口点：

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

**所有 MCP 工具**应使用 `self.resolve_indexer(...)`
替代 `self._services.resolve(Indexer)` — 后者不再工作
（Indexer 不是单例）。

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
├── test_error_handler.py     # 18 个测试 — ToolError, error_boundary
├── test_rate_limiter.py      # 21 个测试 — SlidingWindow, DebounceBatch, CircuitBreaker
├── test_di_container.py      # 13 个测试 — ServiceCollection, 15 个服务
├── test_resource_monitor.py  # 11 个测试 — ResourceMonitor + ProjectIndexerRegistry（v2.3+）
├── test_parser.py            # 4 个测试 — Tree-sitter 解析
├── test_execution_contract.py# 10 个测试 — verify_action
├── test_task_queue.py        # 6 个测试 — 后台任务队列
├── test_branch_aware_index.py# 8 个测试 — get_branch_info
├── test_symbol_index_call_graph.py  # 8 个测试 — 调用图
├── ...（另外 20 个测试文件）
```

**总计：391 个测试。**

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

## 11. 架构不变性

这些规则**不得**被任何新的 PR 违反。

```
1. 工具不直接访问 Registry。
2. 工具不直接读取 Bridge。
3. 工具仅通过 RuntimeCoordinator 工作。
4. RuntimeCoordinator 不知道 Search / Indexer / Memory。
5. ProjectContext — 不可变快照（不启动操作）。
6. 所有系统文件仅通过 SystemArtifacts 确定。
7. 索引器从不索引系统工件。
8. 任何项目路径都通过统一的解析器（resolve_project_root）。
9. 所有 Intel 工具使用 ProjectContext（不是低级 API）。
10. 任何新的运行时组件必须有且只有一个职责。
11. 核心层没有 MCP 导入。
12. 工具不创建依赖 — 全部通过 DI。
13. server.py 仅注册 — 不包含业务逻辑。
```

**代码审查检查：** 任何 PR 都应回答「扩展了哪个现有层？」
的问题。如果答案是「没有，我创建了新的 Manager/Services/Provider」—
这是一个值得暂停的信号。
