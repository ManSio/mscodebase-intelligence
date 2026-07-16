<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](ARCHITECTURE.md) • [🇷🇺 Русский](../ru/ARCHITECTURE.md) • [🇨🇳 中文](../zh/ARCHITECTURE.md)

# MSCodeBase Intelligence — Architecture Guide

> **Version:** 3.2.0  
> **Last updated:** 2026-07-12  
> **Architecture:** 4-Layer Architecture + Graph-Native PropertyGraph Layer + Data Flow Layer (Entry Points → MCP Server/DI → Tool Classes → Core Business Logic → PropertyGraph → Data Flow) with Multi-Window Registry

---

## Table of Contents

1. [Core Principles](#1-core-principles)
2. [Layer Architecture](#2-layer-architecture)
3. [DI Container (ServiceCollection)](#3-di-container)
4. [Tool Layer (42 class-based + 14 intel + 3 diagnostic = 59 total)](#4-tool-layer)
5. [PropertyGraph Layer (v3.0)](#5-propertygraph-layer-v30)
6. [Cypher Query Engine (v3.0)](#6-cypher-query-engine-v30)
7. [Error Handling](#7-error-handling)
8. [Rate Limiting & Resilience](#8-rate-limiting--resilience)
9. [Data Flow: Request → Response](#9-data-flow)
10. [Windows Specifics](#10-windows-specifics)
11. [Multi-Window Registry (v2.3+)](#11-multi-window-registry-v23)
12. [Testing Strategy](#12-testing-strategy)

---

## 1. Core Principles

```
┌──────────────────────────────────────────────────────────────────┐
│              Four Layers of Architecture                          │
│                                                                  │
│  Layer 1: main.py / lsp_main.py  (Entry points, minimal)          │
│  Layer 2: mcp/server.py          (DI routing, tool registration)  │
│  Layer 3: mcp/tools/*.py         (42 class-based tools)           │
│  Layer 4: core/*.py              (Pure business logic)            │
└──────────────────────────────────────────────────────────────────┘
```

**Key rules:**
- **Core layer has NO MCP imports.** It's pure Python with business logic.
- **Tool layer NEVER creates dependencies.** Everything comes from DI.
- **server.py ONLY registers** — no logic, no formatting, no try/except.
- **Dependencies flow downward:** Main ← Server ← Tools ← Core.

---

## 2. Layer Architecture

### 2.0 Ten-Layer Runtime Architecture (v2.4)

```
 Layer 0: Filesystem                  — какие файлы есть на диске?
 Layer 1: SystemArtifacts             — это системный путь?
 Layer 2: Bridge (LSP→MCP)           — какой проект сообщил LSP?
 Layer 3: Registry (IndexerRegistry)  — какой Indexer принадлежит проекту?
 Layer 4: StateMachine (ProjectState) — в каком состоянии проект?
 Layer 5: RuntimeCoordinator          — можно ли выполнять запрос?
 Layer 6: ProjectContext              — как выглядит проект сейчас?
 Layer 7: Passport                    — какой процесс сейчас работает?
 Layer 8: Intel Layer                 — что делать с информацией?
 Layer 9: MCP Tools / AI Agent        — ответ пользователю
```

**Data flow:**
```
Filesystem → SystemArtifacts → Bridge → Registry → StateMachine
                                                          ↓
MCP Tools ← Intel Layer ← ProjectContext ← RuntimeCoordinator
```

**Key rule:** Tool НЕ обращается к Registry, Bridge или Passport напрямую.
Всё — через `RuntimeCoordinator.can_execute()` + `ProjectContext.capture()`.

### 2.1 Entry Points

| File | Protocol | Purpose |
|------|----------|---------|
| `src/main.py` | MCP STDIO | AI-ассистент в Zed Chat |
| `src/lsp_main.py` | LSP STDIO | Индексация через didSave/didChange от Zed |

Both use the same `create_service_collection()` factory.

### 2.2 MCP Server

`src/mcp/server.py` — **~220 lines** (was 3,100 before refactoring).

Responsibilities:
1. Resolve project root (`resolve_project_root()`)
2. Create DI container (`create_service_collection()`)
1. Register 16 core tools + 14 intel_* tools + 3 diagnostic = 33 total
2. Register system prompt (mscodebase-rules)

**No business logic lives here.** Every tool is an import from `mcp/tools/`.

### 2.3 Tool Layer

`src/mcp/tools/*.py` — **11 files, 42 core tools (33 original + 6 write + 1 graph query + 2 graph/analysis).**

Every tool:
- Inherits from `MCPTool` (ABC)
- Receives dependencies via constructor (Constructor Injection)
- Has exactly one entry point: `async def execute(**kwargs) -> dict`
- Is decorated with `@error_boundary(tool_name, timeout_ms)`

```python
class SearchCodeTool(MCPTool):
    """search_code — семантический поиск по коду."""

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
        self.require_index()  # проверка готовности индекса
        # ... логика
```

### 2.4 Core Layer

`src/core/*.py` — **30 files of pure business logic.**

Key modules:

| Module | Purpose | Depends on |
|--------|---------|------------|
| `di_container.py` | DI Container (15+ services) | — |
| `error_handler.py` | ToolError + error_boundary | — |
| `rate_limiter.py` | DebounceBatch + CircuitBreaker | — |
| `indexer.py` | LanceDB vector storage | embedder, file_guard, parser |
| `searcher.py` | Hybrid search (BM25 + Dense + RRF) | indexer, embedder |
| `symbol_index.py` | Call Graph (BFS, PageRank) | parser |
| `graph.py` **(new v3.0)** | **PropertyGraph — SQLite property graph** | — |
| `graph_adapter.py` **(new v3.0)** | **SymbolIndexAdapter wrapping PropertyGraph** | graph, symbol_index |
| `cypher_engine.py` **(new v3.0)** | **Cypher→SQL engine for PropertyGraph** | graph |
| `route_extractor.py` **(new v3.0)** | **HTTP route detection (Flask, FastAPI, Django, Express, Next.js)** | graph |
| `multi_signal_scorer.py` **(new v3.0)** | **Multi-signal search scoring (4 signals)** | graph |
| `dataflow_experiment.py` **(new v3.2)** | **ASSIGNED_FROM edge benchmark & analysis** | parser, graph |
| `intelligence_layer.py` | 14 intel_* tools | indexer, searcher, symbol_index |
| `llama_runner.py` | Lifecycle manager for llama-server.exe (reranker only) | download, launch, stop |
| `remote_embedder.py` | ONNX E5-base INT8 / OpenVINO INT8 (in-process, primary) + LM Studio / Ollama (legacy fallback) | config |
| `parser.py` | Tree-sitter AST | — |
| `file_guard.py` | .gitignore + extension filter | config |

### 2.5 Graph-Native Architecture (v3.0)

```
┌─────────────────────────────────────────────────────────┐
│                    PropertyGraph                         │
│  SQLite (WAL + mmap), nodes/edges, JSON properties       │
│                                                          │
│  nodes(id, name, label, qualified_name, file, properties)│
│  edges(id, src, dst, type, weight, properties)           │
│  — 15 node labels (File, Function, Class, Variable, ...)  │
│  — 28 edge types (CALLS, DEFINES, ASSIGNED_FROM, ...)    │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  CypherEngine     RouteExtractor    MultiSignalScorer   │
│  MATCH→SQL        Flask/FastAPI     4 signals to RRF    │
│  WHERE/RETURN     Django/Express    api_signature        │
│  ORDER BY/LIMIT   Next.js           graph_diffusion      │
│  Dead code det.   Route→HANDLES edge module_proximity    │
│                    in PropertyGraph  cochange_boost       │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────┐
│  Data Flow Layer (v3.2.0)                                         │
│                                                                  │
│  1. Unified Walker — _walk_file()                                │
│     ONE Tree-sitter parse + ONE walk → calls + assignments        │
│     Parse cache avoids re-parsing for same file                   │
│                                                                  │
│  2. Conditional Flow                                              │
│     ASSIGNED_FROM edges have optional condition_path property     │
│     → ["if_statement", "for_statement", "while", "try", "except"] │
│     Tracks if/for/while/try/except nesting                        │
│                                                                  │
│  3. Intra-procedural only                                         │
│     Tracking works within function bodies only                    │
│     Cross-function (a = f(x) → inside f) NOT tracked (explicit)   │
│                                                                  │
│  4. 16 languages for ASSIGNED_FROM                                │
│     Python, Rust, TypeScript, TSX, Go, JavaScript, Java, C#,     │
│     Ruby, PHP, Kotlin, Swift, C, C++, Scala, Dart                │
│                                                                  │
│  5. 30 core files in src/core                                     │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  SymbolIndexAdapter (wrap PropertyGraph → SymbolIndex)   │
│  PURE mode: no in-memory Dict, all data in SQLite        │
|  Full backward compat: all 50 tools unchanged             |
└─────────────────────────────────────────────────────────┘
```

### 2.5 Embedder: E5-base ONNX (in-process)

The MCP server now uses E5-base-v2 via ONNX Runtime (CPU, in-process) as its primary embedder:

- **Model**: `intfloat/e5-base-v2` (768-dim)
- **Runtime**: ONNX (CPU, no GPU required)
- **Architecture**: in-process — no external HTTP server
- **Performance**: ~360 i/s (was 18 i/s with BGE-M3)
- **RAM**: ~265 MB (was 285 MB + VRAM)
- **Config**: `EMBEDDING_DIMENSION=768`, `EMBEDDING_PROVIDER=e5_onnx`

The reranker still runs via llama-server (1 process, not 2).

Legacy fallback providers (LM Studio, Ollama, remote ONNX) remain available via `remote_embedder.py` for custom setups.

---

## 3. DI Container

### 3.1 ServiceCollection

```python
# src/core/di_container.py

services = ServiceCollection()

# Registering a singleton:
services.add_singleton(Indexer, indexer_instance)

# Registering a lazy factory:
services.add_factory(Searcher, lambda s: Searcher(s.resolve(Indexer), ...))

# Resolving:
indexer = services.resolve(Indexer)  # same instance every time
```

### 3.2 Registered Services (15)

| # | Service | Type | Created By |
|---|---------|------|------------|
| 1 | Path (project_root) | singleton | explicit |
| 2 | Path (db_path) | singleton | `_generate_unique_db_path()` |
| 3 | CodeParser | singleton | `CodeParser()` |
| 4 | FileGuard | singleton | `FileGuard(project_root)` |
| 5 | RemoteEmbedder | singleton | `RemoteEmbedder()` |
| 6 | SymbolIndex | singleton | `SymbolIndex()` |
| 7 | SlidingWindowRateLimiter | singleton | `SlidingWindowRateLimiter()` |
| 8 | CircuitBreaker | singleton | `CircuitBreaker(name="lm_studio")` |
| 9 | ProjectRegistry | singleton | `ProjectRegistry()` |
| 10 | MultiProjectSearcher | singleton | `MultiProjectSearcher(embedder, registry)` |
| 11 | ResourceMonitor | singleton | `get_global_resource_monitor()` |
| 12 | ResourceMonitorKey | singleton | `ResourceMonitor` (shared) |
| 13 | ProjectIndexerRegistry | singleton | `ProjectIndexerRegistry(max_cached=5)` |
| 14 | NotificationBroker | singleton | `NotificationBroker()` |
| 15 | IndexerFactoryKey | factory | `_create_indexer_for_path` |

---

## 4. Tool Layer

### 4.1 Tool Registration

In `src/mcp/server.py`:

```python
def _register_all_tools(mcp, services):
    tool_classes = [
        SearchCodeTool, GetSymbolInfoTool,
        NotifyChangeTool, IndexProjectDirTool,
        GetBranchInfoTool, GetIndexStatusTool,
        # ... 39 total
    ]

    for tool_cls in tool_classes:
        instance = tool_cls(services)
        mcp.tool(name=instance.name)(instance.execute)
```

### 4.2 All Tools by Group

| Group | File | Tools |
|-------|------|-------|
| **Search** (3) | `search_tools.py` | search_code, get_symbol_info, impact_analysis |
| **Indexing** (3) | `indexing_tools.py` | notify_change, index_project_dir, index_health |
| **Git** (3) | `git_tools.py` | get_branch_info, get_commit_history, get_file_history |
| **System** (9) | `system_tools.py` | get_index_status, get_index_progress, get_index_timeline, watcher_status, get_logs, get_health_report, predict_eta, run_health_check, read_live_file |
| **Analysis** (5) | `analysis_tools.py` | structural_search, get_repo_map, get_repo_rank, scan_changes, generate_chunk_summaries |
| **Graph** (4) | `graph_tools.py` | cross_repo_search, cross_project_deps, graph_query, get_related_files |
| **Investigation** (3) | `investigation_tools.py` | get_bug_correlation, get_hotspots, find_similar_bugs |
| **Lifecycle** (3) | `lifecycle_tools.py` | submit_background_task, get_task_status, verify_action |
| **Write** (6) | `write_tools.py` | rename_symbol, move_symbol, safe_delete, replace_symbol, insert_before_symbol, insert_after_symbol |
| **Intelligence** (14) | `intelligence_layer.py` | intel_get_runtime_status, intel_get_job_status, intel_code_topology, intel_log_incident, intel_get_project_memory, intel_add_memory_node, intel_get_hotspots, intel_analyze_incident, intel_predict_root_cause, intel_trigger_reindex, intel_get_project_context, intel_explain_project_state, intel_get_telemetry, intel_tool_health |

---

## 5. Error Handling

### 5.1 error_boundary Decorator

Every tool is wrapped with `@error_boundary`:

```python
@error_boundary("tool_name", timeout_ms=15000, max_retries=1)
async def execute(self, **kwargs) -> dict:
    ...
```

It guarantees:
1. **Real timeout** via `asyncio.wait_for(timeout_ms / 1000.0)`
2. **Unified JSON** always: `{"status": "ok"|"error"|"timeout"|"warning", "message": "...", "detail": "...", "latency_ms": 123}`
3. **Controlled errors** (`ToolError`) → return as-is without retry
4. **Unexpected errors** → logged with full traceback, returned as `"status": "error"`
5. **Timeout retry** — configurable via `max_retries`

### 5.2 ToolError Hierarchy

```python
ToolError          # Базовый: status, message, detail, recoverable
├── IndexNotReadyError  # Индекс пуст (warning, recoverable)
└── RateLimitError      # Rate limit превышен (warning, recoverable)
```

---

## 6. Rate Limiting & Resilience

### 6.1 SlidingWindowRateLimiter

```python
limiter = SlidingWindowRateLimiter()  # asyncio.Lock для thread safety

ok = await limiter.acquire("notify_change", max_per_sec=10.0)
if not ok:
    raise RateLimitError(detail="Too many notify_change calls")
```

### 6.2 DebounceBatch

Replaces immediate `searcher.reindex()` on every file change:

```python
batch = DebounceBatch(callback=searcher.reindex, config=DebounceConfig(
    debounce_ms=500,    # 500ms после последнего события
    max_batch_size=100, # или при 100 файлах — немедленный сброс
    max_wait_ms=5000,   # защита от бесконечного debounce
))
await batch.add("file.py")  # BM25 перестроится через 500ms (или при 100 файлах)
```

### 6.3 CircuitBreaker

```python
cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="lm_studio")

result = await cb.call(
    lambda: embedder.embed_batch(texts),
    fallback={"status": "fallback", "message": "LM Studio unavailable"}
)
# States: CLOSED → OPEN (5 failures) → HALF_OPEN (30s later) → CLOSED (success)
```

---

## 7. Data Flow

```
Zed AI Agent
    │
    ▼
MCP Tool Call (e.g., search_code("find indexer"))
    │
    ▼
error_boundary decorator
    ├── timeout check (asyncio.wait_for)
    ├── rate limit check (SlidingWindowRateLimiter)
    └── tool execution
            │
            ▼
    MCPTool.execute(**kwargs)
        │
        ├── self.require_index()  → IndexNotReadyError if empty
        ├── services.resolve(Searcher)
        ├── searcher.search(query)
        │       │
        │       ▼
        │   core/searcher.py
        │       ├── BM25 search (in-memory TF-IDF)
        │       ├── Vector search (LanceDB + ONNX E5-base, in-process)
        │       └── RRF fusion + reranking
        │
        └── return {"status": "ok", "results": [...]}
                │
                ▼
        error_boundary → {"status": "ok", ...latency_ms}
                │
                ▼
        Zed Chat (formatted JSON response)
    ```

    ---

    ## 8. Metadata Enrichment (v2.4.4+)

    ### 8.1 Semantic Compass (MCompassRAG-style)

    Каждый чанк в LanceDB содержит 6 полей метаданных для детерминированной
    фильтрации и multi-granularity retrieval:

    | Поле | Тип | Пример | Назначение |
    |------|-----|--------|------------|
    | `layer` | string | `"core"` | Архитектурный слой: core/mcp/utils/tests/... |
    | `module_name` | string | `"core.parser"` | Логическое имя модуля из пути файла |
    | `hierarchy_level` | string | `"method"` | Уровень: function/method/class/impl/lines |
    | `is_public` | bool | `true` | Публичный/приватный (`_`-префикс) |
    | `symbol_type` | string | `"method_definition"` | AST-тип узла |
    | `parent_id` | string | md5-хеш | Детерминированный хеш родителя |

    Layer detection — автоматическая, по пути файла:

    | Путь | layer |
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
    | прочее | `root` |

    ### 8.2 Flat Tree Hierarchy (SproutRAG-style)

    `parent_id` — детерминированный md5-хеш:

    - **Для метода:** `md5(file_path + "::" + class_name)` — parent = класс
    - **Для функции:** `md5(file_path)` — parent = модуль
    - **Для части гигантской функции:** `md5(file_path + "::" + symbol_name)` — parent = функция

    Позволяет делать multi-granularity retrieval без графовых БД:
    - Найти все функции класса → `get_chunks_by_parent_id("md5_hash")`
    - Подняться до модуля → aggregation по parent_id

    ### 8.3 Layer Filtering в search_code

    ```python
    # Только core-слой
    search_code(query="DI container", filter_layer="core")

    # Только tests
    search_code(query="test_parser", filter_layer="tests")

    # Без фильтра (все слои, как раньше)
    search_code(query="parser")
    ```

    Фильтрация работает на уровне LanceDB `.where(prefilter=True)` — векторный
    поиск идёт только по чанкам нужного слоя. BM25 пост-фильтруется по layer
    из metadata.

    ---

    ## 9. Windows Specifics

### 8.1 Path Resolution

`PROJECT_PATH` may contain `$ZED_WORKTREE_ROOT` literal string (env var not resolved by Zed on Windows).
Solution: `resolve_project_root()` checks 7 fallback strategies:

1. Provided argument
2. LSP→MCP bridge (temp file from LSP, which knows `root_uri`)
3. `PROJECT_PATH` env var (resolved if not `$ZED`)
4. `ext_root` if it's a git repo
5. `ZED_WORKTREE_ROOT` env var
6. CWD (from Zed `settings.json`)
7. `ext_root` as final fallback

### 8.2 Git Subprocess Safety

```python
env["GIT_TERMINAL_PROMPT"] = "0"    # No interactive prompts
env["GIT_ASKPASS"] = "echo"         # No credential helper
env["GIT_PAGER"] = "cat"            # No pager
creationflags = subprocess.CREATE_NO_WINDOW  # No console window
```

### 8.3 Long Path Support

SafePathManager uses `to_win_long_path()` (prepending `\\?\`) for paths > 260 chars.

---

## 9. Multi-Window Registry (v2.3+)

v2.3+ поддерживает **несколько открытых проектов в Zed одновременно**.
Раньше DI хранил singleton `Indexer` — при переключении окон state ломался
(один `file_guard`, один `db_path`, общий `SymbolIndex`).

### 9.1 `ProjectIndexerRegistry`

`src/core/project_indexer_registry.py` — потокобезопасный реестр `Indexer`-ов:

```python
registry = ProjectIndexerRegistry(
    max_cached=5,                      # LRU лимит (5 проектов = 1-2.5GB RAM)
    resource_monitor=get_global_resource_monitor(),  # adaptive throttling
)

# Per-project lazy создание через factory:
def _create_indexer(p: Path) -> Indexer:
    return Indexer(
        db_path=_generate_unique_db_path(p),
        file_guard=FileGuard(p),
        symbol_index=SymbolIndex(),  # изолирован
        project_path=p, ...
    )

services.add_singleton(IndexerFactoryKey, _create_indexer)
indexer = registry.get_indexer(project_path, factory=_create_indexer)
```

**Гарантии:**
- **Изоляция:** каждое окно получает свой `FileGuard`/`SymbolIndex`/`db_path`.
- **LRU:** при открытии 6-го проекта самый старый `Indexer` вытесняется.
- **Pressure-evict:** при RAM > 1GB или CPU > 85% — принудительный evict
  **перед** созданием нового `Indexer` (предотвращает OOM).
- **Cleanup:** `_safe_close()` обнуляет LanceDB connection + `gc.collect()`
  (для Windows mmap handles).

### 9.2 `ResourceMonitor`

`src/core/resource_monitor.py` — stdlib-only мониторинг (без `psutil`):

| Платформа | Метод |
|-----------|-------|
| POSIX | `resource.getrusage(RUSAGE_SELF).ru_maxrss` |
| Windows | `psapi.GetProcessMemoryInfo` через `ctypes` |
| CPU | `resource.getrusage` utime+stime delta / wall-clock |

**Пороги:**
- Soft: 768MB / 75% CPU → throttle индексации (0.1s задержка между файлами)
- Hard: 1024MB / 85% CPU → pressure-evict + 0.5-2s задержка

```python
monitor = get_global_resource_monitor()
snap = monitor.sample()  # ResourceSnapshot (rss_mb, cpu_percent, threads)

if monitor.is_under_pressure():
    delay = monitor.suggest_throttle_delay_sec()
    time.sleep(delay)  # в Indexer.index_project между файлами
```

### 9.3 LSP per-workspace DI

`src/lsp_main.py` хранит **per-workspace** DI-контейнеры:

```python
_services_per_workspace: dict[str, ServiceCollection] = {}

@server.feature("initialize")
async def on_initialize(ls, params):
    project_root = Path(urlparse(params.root_uri).path)
    ls._workspace_uri = params.root_uri
    ls._project_root = project_root
    init_components(project_root, workspace_uri=params.root_uri)
    # → создаёт изолированный DI-контейнер для ОКНА
```

LSP handlers (`did_open`/`did_change`/`did_save`/`did_close`/
`didChangeWatchedFiles`) получают `ls._workspace_uri` и резолвят
правильный `Indexer` через registry.

### 9.4 MCP `resolve_indexer_for_request`

`src/mcp/tools/base.py` — единая точка получения per-project Indexer:

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

**Все MCP-инструменты** должны использовать `self.resolve_indexer(...)`
вместо `self._services.resolve(Indexer)` — последний больше не работает
(Indexer не singleton).

### 9.5 HealthReport `_check_resources`

`src/core/health_report.py` — добавлен метод:

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

## 10. Testing Strategy

```
tests/
├── test_error_handler.py     # 18 tests — ToolError, error_boundary
├── test_rate_limiter.py      # 21 tests — SlidingWindow, DebounceBatch, CircuitBreaker
├── test_di_container.py      # 13 tests — ServiceCollection, 15 services
├── test_resource_monitor.py  # 11 tests — ResourceMonitor + ProjectIndexerRegistry (v2.3+)
├── test_parser.py            # 4 tests — Tree-sitter parsing
├── test_execution_contract.py# 10 tests — verify_action
├── test_task_queue.py        # 6 tests — background task queue
├── test_branch_aware_index.py# 8 tests — get_branch_info
├── test_symbol_index_call_graph.py  # 8 tests — call graph
├── ... (20 more test files)
```

**Total: 396 tests.**

Run:
```bash
pytest tests/ -m "not integration and not benchmark"
```

---

## Quick Reference

| Command | Description |
|---------|-------------|
| `python -m src.main` | Run MCP server (STDIO) |
| `pytest tests/` | Run all tests |
| `pytest tests/test_di_container.py -v` | Run DI container tests only |
| `python -c "from src.mcp.server import create_mcp_server; mcp = create_mcp_server()"` | Verify server loads |

---

## 11. Architectural Invariants

Эти правила НЕ должны нарушаться ни одним новым PR.

```
1. Tool не обращается к Registry напрямую.
2. Tool не читает Bridge напрямую.
3. Tool работает только через RuntimeCoordinator.
4. RuntimeCoordinator не знает про Search / Indexer / Memory.
5. ProjectContext — immutable snapshot (не запускает операций).
6. Все системные файлы определяются только через SystemArtifacts.
7. Индексатор никогда не индексирует системные артефакты.
8. Любой путь проекта проходит через единый resolver (resolve_project_root).
9. Все Intel-инструменты используют ProjectContext (не низкоуровневые API).
10. Любой новый runtime-компонент обязан иметь одну ответственность.
11. Слой Core не имеет MCP-импортов.
12. Инструменты не создают зависимости — всё через DI.
13. server.py регистрирует — не содержит бизнес-логики.
```

**Проверка при code review:** любой PR должен отвечать на вопрос
«Какой существующий слой расширяется?». Если ответ «никакой, я сделал
новый Manager/Services/Provider» — это повод остановиться.
