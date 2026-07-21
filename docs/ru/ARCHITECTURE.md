<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](../en/ARCHITECTURE.md) • [🇷🇺 Русский](ARCHITECTURE.md) • [🇨🇳 中文](../zh/ARCHITECTURE.md)

# MSCodeBase Intelligence — Архитектура

> **Версия:** 3.3.9  
> **Последнее обновление:** 2026-07-21  
> **Архитектура:** 4-слойная архитектура + Graph-Native PropertyGraph Layer + Data Flow Layer (Точки входа → MCP Server/DI → Tool Classes → Core Business Logic → PropertyGraph → Data Flow) с Multi-Window Registry + DocSync

---

## Содержание

1. [Основные принципы](#1-core-principles)
2. [Слойная архитектура](#2-layer-architecture)
3. [DI-контейнер (ServiceCollection)](#3-di-container)
4. [Слой инструментов (18 core + 13 intel + 7 inline + 3 dev + 1 optional = 42 всего)](#4-tool-layer)
5. [Обработка ошибок](#5-error-handling)
6. [Rate Limiting и отказоустойчивость](#6-rate-limiting--resilience)
7. [Поток данных: Запрос → Ответ](#7-data-flow)
8. [Обогащение метаданных (v2.4.4+)](#8-metadata-enrichment-v244)
9. [Особенности Windows](#9-windows-specifics)
10. [Multi-Window Registry (v2.3+)](#10-multi-window-registry-v23)
11. [Стратегия тестирования](#11-testing-strategy)
12. [Архитектурные инварианты](#12-architectural-invariants)

---

## 1. Основные принципы

```
┌──────────────────────────────────────────────────────────────────┐
│              Четыре слоя архитектуры                               │
│                                                                  │
│  Слой 1: main.py / lsp_main.py  (Точки входа, минималистичные)    │
│  Слой 2: mcp/server.py          (DI-маршрутизация, регистрация)   │
│  Слой 3: mcp/tools/*.py         (18 core + 7 inline + 3 dev)     │
│  Слой 4: core/*.py              (Чистая бизнес-логика)            │
└──────────────────────────────────────────────────────────────────┘
```

**Ключевые правила:**
- **Слой Core НЕ имеет MCP-импортов.** Это чистый Python с бизнес-логикой.
- **Слой инструментов НИКОГДА не создаёт зависимости.** Всё приходит из DI.
- **server.py ТОЛЬКО регистрирует** — никакой логики, форматирования, try/except.
- **Зависимости направлены вниз:** Main ← Server ← Tools ← Core.

---

## 2. Слойная архитектура

### 2.0 Десятислойная runtime-архитектура (v2.4)

```
 Слой 0: Filesystem                  — какие файлы есть на диске?
 Слой 1: SystemArtifacts             — это системный путь?
 Слой 2: Bridge (LSP→MCP)           — какой проект сообщил LSP?
 Слой 3: Registry (IndexerRegistry)  — какой Indexer принадлежит проекту?
 Слой 4: StateMachine (ProjectState) — в каком состоянии проект?
 Слой 5: RuntimeCoordinator          — можно ли выполнять запрос?
 Слой 6: ProjectContext              — как выглядит проект сейчас?
 Слой 7: Passport                    — какой процесс сейчас работает?
 Слой 8: Intel Layer                 — что делать с информацией?
 Слой 9: MCP Tools / AI Agent        — ответ пользователю
```

**Поток данных:**
```
Filesystem → SystemArtifacts → Bridge → Registry → StateMachine
                                                          ↓
MCP Tools ← Intel Layer ← ProjectContext ← RuntimeCoordinator
```

**Ключевое правило:** Инструмент НЕ обращается к Registry, Bridge или Passport напрямую.
Всё — через `RuntimeCoordinator.can_execute()` + `ProjectContext.capture()`.

### 2.1 Точки входа

| Файл | Протокол | Назначение |
|------|----------|------------|
| `src/main.py` | MCP STDIO | AI-ассистент в Zed Chat |
| `src/lsp_main.py` *(удалён)* | LSP STDIO | Заменён LSP-клиентом `src/core/lsp_client.py` |

Оба используют одну и ту же фабрику `create_service_collection()`.

### 2.2 MCP-сервер

`src/mcp/server.py` — **~220 строк** (было 3 100 до рефакторинга).

Обязанности:
1. Определить корень проекта (`resolve_project_root()`)
2. Создать DI-контейнер (`create_service_collection()`)
3. Зарегистрировать 18 core + 13 intel + 7 inline + 3 dev + 1 optional = 42 всего
4. Зарегистрировать system prompt (mscodebase-rules)

**Здесь нет бизнес-логики.** Каждый инструмент — импорт из `mcp/tools/`.

### 2.3 Слой инструментов

`src/mcp/tools/*.py` — **14 файлов: 18 core-инструментов + 7 inline + 3 dev + 1 optional (Hub & Spoke: codebase + execute_script + 17 нативных).**

Каждый инструмент:
- Наследуется от `MCPTool` (ABC)
- Получает зависимости через конструктор (Constructor Injection)
- Имеет ровно одну точку входа: `async def execute(**kwargs) -> dict`
- Декорирован `@error_boundary(tool_name, timeout_ms)`

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
        # ... логика поиска
```

### 2.4 Слой ядра

`src/core/*.py` — **30 файлов чистой бизнес-логики.**

Ключевые модули:

| Модуль | Путь | Назначение |
|--------|------|------------|
| `di_container.py` | `src/core/di_container.py` | DI-контейнер (15+ сервисов) |
| `error_handler.py` | `src/core/error_handler.py` | ToolError + error_boundary |
| `rate_limiter.py` | `src/core/rate_limiter.py` | DebounceBatch + CircuitBreaker |
| `engine.py` | `src/core/search/engine.py` | Гибридный поиск (BM25 + Dense + FTS5 + RRF) |
| `graph.py` | `src/core/graph.py` | PropertyGraph — SQLite граф свойств |
| `graph_adapter.py` | `src/core/search/graph_adapter.py` | SymbolIndexAdapter — обёртка PropertyGraph |
| `cypher_engine.py` | `src/core/search/cypher_engine.py` | Cypher→SQL для PropertyGraph |
| `indexer.py` | `src/core/indexing/indexer.py` | LanceDB векторное хранилище + пайплайн индексации |
| `symbol_index.py` | `src/core/indexing/symbol_index.py` | Граф вызовов (BFS, PageRank) |
| `parser.py` | `src/core/indexing/parser.py` | Tree-sitter AST-парсер (16 языков) |
| `file_guard.py` | `src/core/indexing/file_guard.py` | .gitignore + фильтр расширений |
| `db_manager.py` | `src/core/indexing/db_manager.py` | Жизненный цикл таблиц LanceDB (PID-lock, reindex guard) |
| `fts5_mixin.py` | `src/core/search/fts5_mixin.py` | FTS5-миксин полнотекстового поиска |
| `scoring.py` | `src/core/search/scoring.py` | RRF + MMR diversity scoring |
| `layer.py` | `src/core/intelligence/layer.py` | Intel Layer (13 intel_* инструментов) |
| `runtime_coordinator.py` | `src/core/runtime_coordinator.py` | ExecutionVerdict + can_execute() |
| `project_context.py` | `src/core/intelligence/project_context.py` | Снэпшот состояния проекта |
| `llama_runner.py` | `src/providers/reranker/llama_runner.py` | Жизненный цикл llama-server.exe (реранкер) |
| `remote_embedder.py` | `src/providers/embedder/remote_embedder.py` | Эмбеддер ONNX E5-small INT8 + fallback LM Studio/Ollama |
| `doc_sync_engine.py` | `src/core/doc_sync_engine.py` | Автосинхронизация доков с кодом (rename hook) |

### 2.5 Search Engine (v3.3)

```
┌─────────────────────────────────────────────────────────┐
│   Search Pipeline (engine.py)                            │
│                                                          │
│   query_str → embed() → BM25 → FTS5 → 3-way RRF → MMR  │
│                        ↕                                │
│   MultiSignalScorer: api_signature, graph_diffusion,     │
│   module_proximity, cochange_boost                       │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│   PropertyGraph (graph.py)                               │
│   SQLite (WAL + mmap), nodes/edges, JSON properties      │
│   — 15 меток узлов (File, Function, Class, Variable...)  │
│   — 27 типов рёбер (CALLS, DEFINES, ASSIGNED_FROM, ...) │
│   — Cypher query engine (MATCH→SQL)                     │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│   Data Flow Layer (v3.2.0)                               │
│                                                          │
│   1. Unified Walker — один Tree-sitter parse → вызовы +  │
│      присваивания. Parse cache с хэшем содержимого.      │
│   2. Conditional Flow — ASSIGNED_FROM рёбра содержат     │
│      condition_path (if/for/while/try/except)            │
│   3. Только внутри процедур — в пределах тела функций   │
│   4. 16 языков: Python, Rust, TS, TSX, Go, JS,          │
│      Java, C#, Ruby, PHP, Kotlin, Swift, C, C++,        │
│      Scala, Dart                                         │
└─────────────────────────────────────────────────────────┘
```

### 2.6 Эмбеддер: E5-small ONNX (in-process)

MCP-сервер теперь использует multilingual-e5-small через ONNX Runtime (CPU, in-process) как основной эмбеддер:

- **Модель**: `intfloat/multilingual-e5-small` (384-dim)
- **Runtime**: ONNX (CPU, без GPU)
- **Архитектура**: in-process — без внешнего HTTP-сервера
- **Производительность**: ~37 ch/s (было 18 i/s с BGE-M3)
- **RAM**: ~265 MB (было 285 MB + VRAM)
- **Конфиг**: `EMBEDDING_DIMENSION=384`, `EMBEDDING_PROVIDER=e5_onnx`

Реранкер по-прежнему работает через llama-server (1 процесс, не 2).

Legacy fallback-провайдеры (LM Studio, Ollama, remote ONNX) остаются доступны через `remote_embedder.py` для кастомных настроек.

---

## 3. DI-контейнер

### 3.1 ServiceCollection

```python
# src/core/di_container.py

services = ServiceCollection()

# Регистрация синглтона:
services.add_singleton(Indexer, indexer_instance)

# Регистрация ленивой фабрики:
services.add_factory(Searcher, lambda s: Searcher(s.resolve(Indexer), ...))

# Разрешение:
indexer = services.resolve(Indexer)  # каждый раз тот же экземпляр
```

### 3.2 Зарегистрированные сервисы (15)

| # | Сервис | Тип | Создаётся |
|---|--------|-----|-----------|
| 1 | Path (project_root) | singleton | явно |
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

## 4. Слой инструментов

### 4.1 Регистрация инструментов

В `src/mcp/server_tools.py`:

```python
def register_all_tools(mcp, services):
    tool_classes = [
        # Search (3)
        SearchCodeTool, GetSymbolInfoTool, ImpactAnalysisTool,
        # Hub: codebase (write/index/git/notify — мультиплексирован по action)
        CodebaseTool,
        # Spoke: E2B-песочница
        ExecuteScriptTool,
        # Analysis (5)
        StructuralSearchTool, GetRepoMapTool, GetRepoRankTool,
        ScanChangesTool, GenerateChunkSummariesTool,
        # Graph (3 — Фаза 2: graph_query мультиплексирует cypher + related + flow)
        CrossRepoSearchTool, CrossProjectDepsTool, GraphQueryTool,
        # Investigation (3)
        GetBugCorrelationTool, GetHotspotsTool, FindSimilarBugsTool,
        # Lifecycle (3)
        SubmitBackgroundTaskTool, GetTaskStatusTool, VerifyActionTool,
    ]
    # +13 intel_* инструментов + 7 inline diagnostic + 3 dev + 1 optional
    # Всего: 42 зарегистрировано (18 core + 13 intel + 7 inline + 3 dev + 1 optional)
```

**Фильтр видимости инструментов:** По умолчанию видимо ~16 инструментов. Установите `MSCODEBASE_MCP_TOOLS=""` чтобы показать все 42.

### 4.2 Все инструменты по группам

| Группа | Файл | Инструменты |
|--------|------|-------------|
| **Поиск** (3) | `search_tools.py` | search_code, get_symbol_info, impact_analysis |
| **Hub: codebase** (1) | `codebase_tool.py` | codebase(action=rename/move/delete/replace/insert/notify/index/git) |
| **Spoke: E2B** (1) | `codebase_tool.py` | execute_script(code) |
| **Анализ** (5) | `analysis_tools.py` | structural_search, get_repo_map, get_repo_rank, scan_changes, generate_chunk_summaries |
| **Граф** (3) | `graph_tools.py` | cross_repo_search, cross_project_deps, graph_query |
| **Расследование** (3) | `investigation_tools.py` | get_bug_correlation, get_hotspots, find_similar_bugs |
| **Жизненный цикл** (3) | `lifecycle_tools.py` | submit_background_task, get_task_status, verify_action |
| **Write** (1) | `write_tools.py` | codebase(action={rename,move,delete,replace,insert,impact}) |
| **Индексация** (1) | `indexing_tools.py` | get_index_status, notify_change, watcher_status |
| **Git** (1) | `git_tools.py` | git(action={log,history,branch}) |
| **Документация** (1) | `doc_tools.py` | generate_docs, bump_version, auto_update_docs, install_git_hooks |
| **Meta** (1) | `meta_tools.py` | get_index_status, get_index_progress, get_index_timeline, get_health_report, get_logs |
| **Система** (1) | `system_tools.py` | read_live_file, get_health_report, get_logs |
| **Intelligence** (13) | `intelligence/layer.py` | intel_get_runtime_status, intel_get_job_status, intel_code_topology, intel_log_incident, intel_get_project_memory, intel_add_memory_node, intel_get_hotspots, intel_analyze_incident, intel_predict_root_cause, intel_trigger_reindex, intel_get_project_context, intel_explain_project_state, intel_get_telemetry, intel_tool_health |
| **Diagnostic inline** (7) | `server_tools.py` | debug_runtime_passport, get_runtime_counters, intel_execution_timeline, get_health_report, get_logs, read_live_file, stale_detector |

> **Всего:** 42 зарегистрировано (18 core + 13 intel + 7 inline + 3 dev + 1 optional). По умолчанию видимо: ~16. Показать все: `MSCODEBASE_MCP_TOOLS=""`.

## 5. Обработка ошибок

### 5.1 Декоратор error_boundary

Каждый инструмент обёрнут в `@error_boundary`:

```python
@error_boundary("tool_name", timeout_ms=15000, max_retries=1)
async def execute(self, **kwargs) -> dict:
    ...
```

Гарантирует:
1. **Реальный таймаут** через `asyncio.wait_for(timeout_ms / 1000.0)`
2. **Унифицированный JSON** всегда: `{"status": "ok"|"error"|"timeout"|"warning", "message": "...", "detail": "...", "latency_ms": 123}`
3. **Контролируемые ошибки** (`ToolError`) → возврат как есть, без повтора
4. **Неожиданные ошибки** → логируются с полным traceback, возвращаются как `"status": "error"`
5. **Повтор при таймауте** — настраивается через `max_retries`

### 5.2 Иерархия ToolError

```python
ToolError          # Базовый: status, message, detail, recoverable
├── IndexNotReadyError  # Индекс пуст (warning, recoverable)
└── RateLimitError      # Превышен rate limit (warning, recoverable)
```

---

## 6. Rate Limiting и отказоустойчивость

### 6.1 SlidingWindowRateLimiter

```python
limiter = SlidingWindowRateLimiter()  # asyncio.Lock для thread safety

ok = await limiter.acquire("notify_change", max_per_sec=10.0)
if not ok:
    raise RateLimitError(detail="Слишком много вызовов notify_change")
```

### 6.2 DebounceBatch

Заменяет немедленный `searcher.reindex()` при каждом изменении файла:

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
    fallback={"status": "fallback", "message": "LM Studio недоступен"}
)
# Состояния: CLOSED → OPEN (5 ошибок) → HALF_OPEN (через 30s) → CLOSED (успех)
```

---

## 7. Поток данных

```
Zed AI Agent
    │
    ▼
MCP Tool Call (например, search_code("find indexer"))
    │
    ▼
error_boundary decorator
    ├── проверка таймаута (asyncio.wait_for)
    ├── проверка rate limit (SlidingWindowRateLimiter)
    └── выполнение инструмента
            │
            ▼
    MCPTool.execute(**kwargs)
        │
        ├── self.require_index()  → IndexNotReadyError если пуст
        ├── services.resolve(Searcher)
        ├── engine.hybrid_search(query)
        │       │
        │       ▼
        │   core/search/engine.py
        │       ├── BM25 search (in-memory TF-IDF)
        │       ├── Vector search (LanceDB + ONNX E5-small, in-process)
        │       ├── FTS5 search (SQLite FTS5, trigram+porter)
        │       └── 3-way RRF fusion + MMR diversity
        │
        └── return {"status": "ok", "results": [...]}
                │
                ▼
        error_boundary → {"status": "ok", ...latency_ms}
                │
                ▼
        Zed Chat (форматированный JSON-ответ)
```

---

## 8. Обогащение метаданных (v2.4.4+)

### 8.1 Метаданные чанка

Каждый чанк в LanceDB хранит 6 полей метаданных для детерминированной
фильтрации и multi-granularity retrieval:

| Поле | Тип | Пример | Назначение |
|------|-----|--------|------------|
| `layer` | string | `"core"` | Архитектурный слой: core/mcp/utils/tests/... |
| `module_name` | string | `"core.parser"` | Логическое имя модуля из пути файла |
| `hierarchy_level` | string | `"method"` | Уровень: function/method/class/impl/lines |
| `is_public` | bool | `true` | Публичный/приватный (`_`-префикс) |
| `symbol_type` | string | `"method_definition"` | AST-тип узла |
| `parent_id` | string | md5-хеш | Детерминированный хеш родителя |

Определение слоя — автоматическое, по пути файла:

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

Позволяет делать multi-granularity retrieval без графовой БД:
- Найти все методы класса → `get_chunks_by_parent_id("md5_hash")`
- Подняться до модуля → aggregation по parent_id

### 8.3 Фильтрация по слою в search_code

```python
# Только core-слой
search_code(query="DI container", filter_layer="core")

# Только tests
search_code(query="test_parser", filter_layer="tests")

# Без фильтра (все слои, как раньше)
search_code(query="parser")
```

Фильтрация по слою работает на уровне LanceDB через `.where(prefilter=True)` — векторный поиск идёт только по чанкам указанного слоя. BM25 пост-фильтруется по layer из metadata.

---

## 9. Особенности Windows

### 9.1 Разрешение путей

`PROJECT_PATH` может содержать литерал `$ZED_WORKTREE_ROOT` (env var не разрешается Zed на Windows).
Решение: `resolve_project_root()` проверяет 7 fallback-стратегий:

1. Переданный аргумент
2. LSP→MCP bridge (временный файл от LSP, который знает `root_uri`)
3. `PROJECT_PATH` env var (разрешается, если не `$ZED`)
4. `ext_root`, если это git-репозиторий
5. `ZED_WORKTREE_ROOT` env var
6. CWD (из Zed `settings.json`)
7. `ext_root` как финальный fallback

### 9.2 Безопасность git-подпроцессов

```python
env["GIT_TERMINAL_PROMPT"] = "0"    # Нет интерактивных запросов
env["GIT_ASKPASS"] = "echo"         # Нет credential helper
env["GIT_PAGER"] = "cat"            # Нет пейджера
creationflags = subprocess.CREATE_NO_WINDOW  # Нет консольного окна
```

### 9.3 Поддержка длинных путей

SafePathManager использует `to_win_long_path()` (добавление `\\?\`) для путей длиннее 260 символов.

---

## 10. Multi-Window Registry (v2.3+)

v2.3+ поддерживает **несколько открытых проектов в Zed одновременно**.
Раньше DI хранил singleton `Indexer` — при переключении окон state ломался
(один `file_guard`, один `db_path`, общий `SymbolIndex`).

### 10.1 `ProjectIndexerRegistry`

`src/core/indexing/project_indexer_registry.py` — потокобезопасный реестр объектов `Indexer`:

```python
registry = ProjectIndexerRegistry(
    max_cached=5,                      # LRU лимит (5 проектов = 1-2.5GB RAM)
    resource_monitor=get_global_resource_monitor(),  # adaptive throttling
)

# Per-project ленивое создание через factory:
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

### 10.2 `ResourceMonitor`

`src/core/indexing/resource_monitor.py` — stdlib-only мониторинг (без `psutil`):

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

### 10.3 LSP per-workspace DI

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

LSP-обработчики (`did_open`/`did_change`/`did_save`/`did_close`/
`didChangeWatchedFiles`) получают `ls._workspace_uri` и резолвят
правильный `Indexer` через registry.

### 10.4 MCP `resolve_indexer_for_request`

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

### 10.5 HealthReport `_check_resources`

`src/core/code_health.py` — добавлен метод:

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

## 11. Стратегия тестирования

```
tests/
├── test_error_handler.py     # 18 тестов — ToolError, error_boundary
├── test_rate_limiter.py      # 21 тестов — SlidingWindow, DebounceBatch, CircuitBreaker
├── test_di_container.py      # 13 тестов — ServiceCollection, 15 services
├── test_resource_monitor.py  # 11 тестов — ResourceMonitor + ProjectIndexerRegistry (v2.3+)
├── test_parser.py            # 4 теста — Tree-sitter парсинг
├── test_execution_contract.py# 10 тестов — verify_action
├── test_task_queue.py        # 6 тестов — очередь фоновых задач
├── test_branch_aware_index.py# 8 тестов — get_branch_info
├── test_symbol_index_call_graph.py  # 8 тестов — граф вызовов
├── ... (ещё 20 тестовых файлов)
```

**Всего: 396 тестов.**

Запуск:
```bash
pytest tests/ -m "not integration and not benchmark"
```

---

## Быстрая справка

| Команда | Описание |
|---------|----------|
| `python -m src.main` | Запуск MCP-сервера (STDIO) |
| `pytest tests/` | Запуск всех тестов |
| `pytest tests/test_di_container.py -v` | Только тесты DI-контейнера |
| `python -c "from src.mcp.server import create_mcp_server; mcp = create_mcp_server()"` | Проверка загрузки сервера |

---

## 12. Архитектурные инварианты

Эти правила НЕ должны нарушаться ни одним новым PR.

```
1. Инструмент не обращается к Registry напрямую.
2. Инструмент не читает Bridge напрямую.
3. Инструмент работает только через RuntimeCoordinator.
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
