<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[English](../en/ARCHITECTURE.md) · [Русский](ARCHITECTURE.md) · [中文](../zh/ARCHITECTURE.md)

# MSCodeBase Intelligence — Архитектура

> **Актуально на 2026-10-25.** Документ описывает дефолтный Phase 3 runtime:
> SQLite FTS5/BM25 плюс PropertyGraph. Эмбеддинги, реранкинг и LanceDB/vector
> path опциональны и отмечены явно.

---

## 1. Цели дизайна

Сервер даёт AI-ассистенту обоснованные локальные ответы о кодовой базе, не
делая удалённый сервис или большую модель обязательными.

1. **Local-first.** Поиск, граф и память проекта работают без сети.
2. **Deterministic before probabilistic.** Точные символы, пути и BM25
   проверяются раньше опциональных semantic-слоёв.
3. **Fail open, not silent.** Нет embedder, пустой граф или stale index должны
   давать диагноз, а не выдуманный ответ.
4. **Один контракт для людей и агентов.** Одна tool schema для Zed, скриптов и
   тестов.
5. **Observable.** Runtime passport, index status, health report и logs —
   полноценные инструменты, не debug-приложение.

## 2. Runtime в двух словах

```text
Zed
 ├── built-in LSP (autocomplete, diagnostics)
 └── MCP client
      │
      ▼
 src/main.py (stdio) или src/remote_main.py (HTTP)
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

`<data_root>` — `%LOCALAPPDATA%/mscodebase` на Windows или платформенный
эквивалент. Артефакты проекта лежат вне репозитория; `chunks.db` — единственный
store внутри директории проекта.

## 3. Слои

| Слой | Ответственность | Основные модули |
|---|---|---|
| Entry | Старт процесса, project root, stdio/HTTP | `src/main.py`, `src/remote_main.py` |
| Protocol | MCP server, lifecycle, hooks | `src/mcp/server.py`, `server_factory.py` |
| Tool | Тонкие адаптеры: валидация, формат, error boundary | `src/mcp/tools/*.py`, `server_tools.py` |
| Core | Search, indexing, graph, memory, write guards | `src/core/*` |
| Providers | Опциональные embedders, rerankers, LSP | `src/providers/*`, `src/core/lsp_client.py` |
| Storage | SQLite/FTS5, PropertyGraph, JSON memory, logs | `chunk_store.py`, `graph.py`, `intelligence/` |

Tool layer не реализует ranking или parsing сам. Он резолвит project-scoped
service и делегирует в core.

## 4. Точки входа и lifecycle

- `src/main.py` — stdio MCP server для Zed extension. Определяет extension/
  project root, настраивает logging, запускает server loop.
- `src/remote_main.py` — тот же сервер через authenticated HTTP transport.
  Опционален и выключен без конфигурации.
- `src/mcp/server_factory.py` — создаёт сервер, DI container, регистрирует
  tools, notifications и shutdown handlers.
- `src/mcp/server_tools.py` — регистрация и allowlist.

Второй проект в другом окне Zed изолируется `ProjectIndexerRegistry`: у каждого
проекта свои indexer/searcher/graph handles, LRU-лимит и resource monitoring.

## 5. Dependency injection

`src/core/di_container.py` даёт `ServiceCollection` и
`create_service_collection(project_root)`. Сервисы — singletons в рамках
процесса:

- project root и parser;
- indexer/searcher и опциональный embedder;
- PropertyGraph и symbol index;
- `ProjectIndexerRegistry` / `MultiProjectSearcher`;
- rate limiter, circuit breaker, notification broker.

Tool classes получают collection через constructor injection. Они не создают
indexer и не открывают БД напрямую. Shutdown закрывает ресурсы и фоновые задачи.

## 6. Tool layer

Сервер регистрирует **64 инструмента**:

- 31 core tool class (search, LSP, graph, analysis, write, lifecycle);
- 16 `intel_*`;
- 13 inline diagnostic;
- 4 dev.

`execute_script` — 65-й опциональный инструмент, только при
`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`. Default allowlist показывает **49**;
`MSCODEBASE_MCP_TOOLS` управляет видимостью (пусто — все зарегистрированные).

`codebase(action=...)` — hub над index, git и write. У поиска есть
`search_code` и `plan_search`, который возвращает детерминированный план
(primary query, exact tokens, symbols, concepts, intent).

Все tools обёрнуты в `error_boundary`: timeout, telemetry и structured error
вместо зависшего MCP loop.

## 7. Indexing pipeline

```text
discover files
  → FileGuard (extensions, size, binaries, system dirs, .gitignore)
  → parser (Tree-sitter; language-specific extractors)
  → chunks + symbols + calls/imports/assignments/decorators/overrides
  → SQLiteChunkStore (text + FTS5) and PropertyGraph
```

Правила:

- `experiments/**` **исключён из индекса**. Там frozen-панели и run artifacts;
  их индексация заставляла BM25 возвращать саму панель вместо кода. Файлы
  остаются в git.
- Incremental indexing обновляет chunks и graph rows файла одной транзакцией.
- Полный vector reindex намеренно блокируется при
  `MSCODEBASE_DENSE_OFF=true`. Используйте `scripts/reindex_text_only.py` для
  текста и `scripts/rebuild_graph.py` для графа.
- `build_head` пишется только после полного успешного индекса, чтобы freshness
  можно было сверить с git HEAD.
- `FileGuard` и `SafePathManager` отсекают пути вне проекта и системные
  директории до parsing.

## 8. Storage

| Store | Путь | Назначение |
|---|---|---|
| Chunk store | `<project>/.mscodebase/chunks.db` | Текст, metadata, FTS5 |
| Graph | `<data_root>/projects/<hash>/graph.db` | Символы, файлы, typed edges |
| Memory | `<data_root>/projects/<hash>/intelligence/` | Память, инциденты, jobs |
| Logs | `<data_root>/logs/` | Диагностика сервера и tools |

LanceDB — legacy/optional vector store. Дефолтный text-first путь её не требует
и не использует как основной источник candidates при
`MSCODEBASE_SQLITE_CHUNKS=true`.

## 9. Интеграция поиска

Поиск — крупнейшая core-подсистема. Дефолтный путь:

1. SQLite FTS5/BM25 candidates;
2. опциональный symbol/graph stage для identifier-shaped запросов;
3. опциональный on-demand rerank;
4. exact-name boost и symbol deduplication;
5. docs routing на уровне tool при сильном BM25-разрыве.

Полный RRF/MMR/anchor pipeline в `core/search/engine.py` относится к
опциональному dense/LanceDB path или старым путям. Он не применяется молча к
каждому Phase 3 запросу. Точное разделение — в
[SEARCH_PIPELINE.md](SEARCH_PIPELINE.md).

## 10. Intelligence и память

`core/intelligence/` реализует память проекта и инциденты:

- ADR и known issues хранятся как записи со статусом и evidence;
- инциденты можно логировать, искать и предсказывать по runtime data;
- `verify-on-read` помечает факты как verified/refuted/superseded;
- retraction/supersede сохраняют историю вместо удаления.

Память локальна и project-scoped. Это не общий chat log.

## 11. Записи и безопасность

Write tools (`rename`, `move`, `safe_delete`, `replace`, `insert_before/after`)
работают с символами, а не с сырым текстом. Pipeline:

1. resolve symbol и references;
2. impact summary;
3. `ack_impact`, если файл load-bearing;
4. preview;
5. apply только с `apply=true`, затем refresh chunks/graph.

Cross-file rename может использовать basedpyright LSP; при timeout —
fallback на SymbolIndex. `execute_script` выключен по умолчанию; при включении
использует AST validation, import wrapper и subprocess sandbox.

## 12. Concurrency и multi-window

- Один indexer/searcher на проект через registry.
- SQLite writes сериализуются lock'ом chunk store; reads безопасны между
  потоками.
- Background indexing использует watchdog heartbeat и job state: агент
  опрашивает статус, не блокируя редактор.
- Внешние процессы — `Popen` + `communicate(timeout=...)`, не
  `capture_output` в daemon threads (Windows pipe deadlock).
- Reindex fast-fail возвращает понятную ошибку вместо зависания.

## 13. Отказы и операционные проверки

| Симптом | Первая проверка | Исправление |
|---|---|---|
| Graph tools пусты | nodes/edges в `graph.db` | `python scripts/rebuild_graph.py` |
| Поиск возвращает experiment docs | в индексе есть `experiments/**` | reindex; FileGuard их исключает |
| Docs всегда мимо | gold `docs/en`, ответ `docs/ru` | нормализовать по basename |
| Index stale | `codebase(action="index", path="status")` | `scripts/reindex_text_only.py` |
| Embedder missing | `debug_runtime_passport()` | text path работает; настроить provider |
| Tools не видны | `MSCODEBASE_MCP_TOOLS` | добавить имена или пустое значение |

## 14. Тесты и проверка

- `pytest tests/` — unit/integration suite; markers разделяют integration и
  benchmark.
- `python scripts/smoke_e2e.py --project .` — реальные embed/rerank/search без
  моков, когда providers доступны.
- `scripts/rebuild_graph.py` и `scripts/reindex_text_only.py` — штатные пути
  починки graph/index drift.
- Search experiments — в `experiments/` с frozen inputs и raw runs; это источник
  чисел качества в README.

## 15. Связанные документы

- [SEARCH_PIPELINE.md](SEARCH_PIPELINE.md) — retrieval, ranking, modes и limits.
- [ARCHITECTURE_DEEP.md](ARCHITECTURE_DEEP.md) — исторический deep dive и
  опциональные детали.
- [GRACEFUL_DEGRADATION.md](GRACEFUL_DEGRADATION.md) — поведение без providers.
- [INSTALL.md](INSTALL.md) — установка и команды починки.
- [README.md](../../README.md) — текущий публичный контракт и качество.
