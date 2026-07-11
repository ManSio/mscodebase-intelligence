<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](../en/ARCHITECTURE.md) • [🇷🇺 Русский](ARCHITECTURE.md) • [🇨🇳 中文](../zh/ARCHITECTURE.md)

# MSCodeBase Intelligence — Архитектура

> **Версия:** 3.2.0  
> **Последнее обновление:** 2026-07-12  
> **Архитектура:** 4-слойная архитектура + PropertyGraph + Data Flow Layer с Multi-Window Registry

---

## Содержание

1. [Основные принципы](#1-core-principles)
2. [Слойная архитектура](#2-layer-architecture)
3. [DI-контейнер (ServiceCollection)](#3-di-container)
4. [Слой инструментов (41 class-based + 14 intel + 3 diagnostic = 58 всего)](#4-tool-layer)
5. [Обработка ошибок](#5-error-handling)
6. [Rate Limiting и отказоустойчивость](#6-rate-limiting--resilience)
7. [Поток данных: Запрос → Ответ](#7-data-flow)
8. [Особенности Windows](#8-windows-specifics)
9. [Multi-Window Registry (v2.3+)](#9-multi-window-registry-v23)
10. [Стратегия тестирования](#10-testing-strategy)

---

## 1. Основные принципы

```
┌──────────────────────────────────────────────────────────────────┐
│              Четыре слоя архитектуры                               │
│                                                                  │
│  Слой 1: main.py / lsp_main.py  (Точки входа, минималистичные)    │
│  Слой 2: mcp/server.py          (DI-маршрутизация, регистрация)   │
│  Слой 3: mcp/tools/*.py         (40 class-based инструментов)      │
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
| `src/lsp_main.py` | LSP STDIO | Индексация через didSave/didChange от Zed |

Оба используют одну и ту же фабрику `create_service_collection()`.

### 2.2 MCP-сервер

`src/mcp/server.py` — **~220 строк** (было 3 100 до рефакторинга).

Обязанности:
1. Определить корень проекта (`resolve_project_root()`)
2. Создать DI-контейнер (`create_service_collection()`)
3. Зарегистрировать 33 инструмента + 14 intel_* + 3 diagnostic
4. Зарегистрировать system prompt (mscodebase-rules)

**Здесь нет бизнес-логики.** Каждый инструмент — импорт из `mcp/tools/`.

### 2.3 Слой инструментов

`src/mcp/tools/*.py` — **11 файлов, 39 основных инструментов (33 исходных + 6 write).**

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
        # ... логика
```

### 2.4 Слой ядра

`src/core/*.py` — **30 файлов чистой бизнес-логики.**

Ключевые модули:

| Модуль | Назначение | Зависит от |
|--------|------------|------------|
| `di_container.py` | DI-контейнер (15 сервисов) | — |
| `error_handler.py` | ToolError + error_boundary | — |
| `rate_limiter.py` | DebounceBatch + CircuitBreaker | — |
| `indexer.py` | LanceDB векторное хранилище | embedder, file_guard, parser |
| `searcher.py` | Гибридный поиск (BM25 + Dense + RRF) | indexer, embedder |
| `symbol_index.py` | Граф вызовов (BFS, PageRank) | parser |
| `graph.py` **(новое v3.0)** | **PropertyGraph — SQLite граф** | — |
| `graph_adapter.py` **(новое v3.0)** | **SymbolIndexAdapter обёртка PropertyGraph** | graph, symbol_index |
| `cypher_engine.py` **(новое v3.0)** | **Cypher→SQL для PropertyGraph** | graph |
| `route_extractor.py` **(новое v3.0)** | **HTTP Route детекция** | graph |
| `multi_signal_scorer.py` **(новое v3.0)** | **Мульти-сигнальное ранжирование (4 сигнала)** | graph |
| `dataflow_experiment.py` **(новое v3.2)** | **Бенчмарк ASSIGNED_FROM** | parser |
| `intelligence_layer.py` | 14 intel_* инструментов | indexer, searcher, symbol_index |
| `llama_runner.py` | Менеджер lifecycle для llama-server.exe | download, launch, stop |
| `remote_embedder.py` | LM Studio / llama.cpp / Ollama / ONNX | config |
| `parser.py` | Tree-sitter AST | — |
| `file_guard.py` | .gitignore + фильтр расширений | config |

### 2.5 Data Flow Layer (v3.2.0)

```
┌──────────────────────────────────────────────────────────────────┐
│  Data Flow Layer                                                 │
│                                                                  │
│  1. Unified Walker — _walk_file()                                │
│     ОДИН Tree-sitter parse + ОДИН обход → вызовы + присваивания  │
│     Parse cache: повторный вызов для того же файла — без парсинга │
│                                                                  │
│  2. Conditional Flow                                             │
│     ASSIGNED_FROM рёбра содержат condition_path                  │
│     → ["if_statement", "for_statement", "try", "except"]         │
│     Отслеживает вложенность if/for/while/try                     │
│                                                                  │
│  3. Только внутри функций                                        │
│     Отслеживание работает в пределах тела функции                 │
│     Межпроцедурный поток НЕ отслеживается (явное ограничение)      │
│                                                                  │
│  4. Пока только Python                                           │
│     Парсеры для Rust/TS есть, но типы assignment-узлов разные     │
│                                                                  │
│  5. 30 файлов в src/core                                         │
└──────────────────────────────────────────────────────────────────┘
```

### 2.6 Приоритет провайдеров

MCP-сервер авто-детектирует лучший доступный провайдер эмбеддингов:

1. **LM Studio** — наивысшее качество, требует внешний сервер
2. **llama.cpp** — встроенный, авто-устанавливается через `install.py` (GGUF модели)
3. **ONNX server** — ONNX runtime с удалёнными моделями
4. **local ONNX** — CPU-only fallback, наименьшее качество

Приоритет оценивается при запуске. llama.cpp обеспечивает снижение RAM в 5,3× (227 MB против 1200 MB) по сравнению с LM Studio.

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

В `src/mcp/server.py`:

```python
def _register_all_tools(mcp, services):
    tool_classes = [
        SearchCodeTool, GetSymbolInfoTool,
        NotifyChangeTool, IndexProjectDirTool,
        GetBranchInfoTool, GetIndexStatusTool,
        # ... всего 39
    ]

    for tool_cls in tool_classes:
        instance = tool_cls(services)
        mcp.tool(name=instance.name)(instance.execute)
```

### 4.2 Все инструменты по группам

| Группа | Файл | Инструменты |
|--------|------|-------------|
| **Поиск** (3) | `search_tools.py` | search_code, get_symbol_info, impact_analysis |
| **Индексация** (3) | `indexing_tools.py` | notify_change, index_project_dir, index_health |
| **Git** (3) | `git_tools.py` | get_branch_info, get_commit_history, get_file_history |
| **Системные** (9) | `system_tools.py` | get_index_status, get_index_progress, get_index_timeline, watcher_status, get_logs, get_health_report, predict_eta, run_health_check, read_live_file |
| **Анализ** (5) | `analysis_tools.py` | structural_search, get_repo_map, get_repo_rank, scan_changes, generate_chunk_summaries |
| **Граф** (4) | `graph_tools.py` | cross_repo_search, cross_project_deps, graph_query, get_related_files |
| **Расследование** (3) | `investigation_tools.py` | get_bug_correlation, get_hotspots, find_similar_bugs |
| **Жизненный цикл** (3) | `lifecycle_tools.py` | submit_background_task, get_task_status, verify_action |
| **Write** (6) | `write_tools.py` | rename_symbol, move_symbol, safe_delete, replace_symbol, insert_before_symbol, insert_after_symbol |
| **Intelligence** (14) | `intelligence_layer.py` | intel_get_runtime_status, intel_get_job_status, intel_code_topology, intel_log_incident, intel_get_project_memory, intel_add_memory_node, intel_get_hotspots, intel_analyze_incident, intel_predict_root_cause, intel_trigger_reindex, intel_get_project_context, intel_explain_project_state, intel_get_telemetry, intel_tool_health |

---

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
└── RateLimitError      # Rate limit превышен (warning, recoverable)
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
        ├── searcher.search(query)
        │       │
        │       ▼
        │   core/searcher.py
        │       ├── BM25 search (in-memory TF-IDF)
        │       ├── Vector search (LanceDB + LM Studio)
        │       └── RRF fusion + реранжирование
        │
        └── return {"status": "ok", "results": [...]}
                │
                ▼
        error_boundary → {"status": "ok", ...latency_ms}
                │
                ▼
        Zed Chat (форматированный JSON-ответ)
---

## 8. Обогащение метаданных (v2.4.4+)

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

### 10.2 `ResourceMonitor`

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
