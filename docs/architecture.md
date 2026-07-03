# 📑 ТЕХНИЧЕСКИЙ ПАСПОРТ И АРХИТЕКТУРА

## 1. Спецификация тестового стенда

| Параметр | Значение |
|----------|----------|
| CPU | AMD Ryzen 5 5600H (6 ядер / 12 потоков, 3.3–4.2 GHz) |
| RAM | 16 GB DDR4 (3200 MHz) |
| GPU | AMD Radeon Graphics (встроенная) |
| Диск | SSD 341 GB (NTFS), диск `D:` |
| OS | Windows 11 Home Insider Preview |

## 2. Векторное окружение

| Компонент | Значение |
|-----------|----------|
| Модель эмбеддингов | `text-embedding-bge-m3` (1024 dim) |
| Протокол | LM Studio OpenAI-совместимый API (`/v1/embeddings`) |
| Реранкинг | Multi-Provider (Ollama `:11434` → LM Studio `:1234` → RRF fallback) |
| СУБД хранилище | LanceDB v2 (Apache Arrow) |

## 3. Топология данных

Векторные индексы изолированы по проектам:

```
<PARENT_DIR>/.codebase_indices/lancedb_v2/index_<project>_<hash>.db
```

### Структура путей (Windows)

```python
# src/core/indexer.py → _generate_unique_db_path()
normalized_path = str(project_path.resolve()).lower().replace('\\', '/')
project_hash = hashlib.md5(normalized_path.encode()).hexdigest()[:8]
db_dir = project_path.parent / ".codebase_indices" / "lancedb_v2"
db_name = f"index_{project_name}_{project_hash}.db"
```

## 4. Архитектура системы

### 4.1. Потоки данных (Hybrid LSP + MCP)

```
                        ┌──────────────────────────────────────┐
                        │         hybrid_server.py            │
                        │    (LSP stdio + MCP HTTP/SSE)       │
                        │         Единый процесс              │
                        └──────────────────────────────────────┘
                           │                    │
              ┌────────────┴────────┐          │
              ▼                     ▼          ▼
       ┌─────────────┐      ┌──────────────┐  ┌─────────────────┐
       │  Zed IDE    │      │  MCP Tools   │  │  RemoteEmbedder │
       │ (LSP client)│      │  (AI Agent)  │  │  (LM Studio)    │
       └─────────────┘      └──────────────┘  └─────────────────┘
              │                    │
              ▼                    ▼
       ┌──────────────────────────────────────┐
       │          Общая память процесса        │
       │  ┌────────────┐  ┌────────────────┐  │
       │  │  Indexer   │  │  SymbolIndex   │  │
       │  │ (LanceDB)  │  │  (Call Graph)  │  │
       │  └────────────┘  └────────────────┘  │
       └──────────────────────────────────────┘
```

### 4.2. Модули

| Модуль | Файл | Назначение |
|--------|------|------------|
| Hybrid Server | `src/hybrid_server.py` | Главная точка входа: LSP + MCP в одном процессе |
| LSP Server (legacy) | `src/lsp_main.py` | Автономный LSP-сервер (сохранён для обратной совместимости) |
| MCP Server (legacy) | `src/main.py` | Автономный MCP-сервер (сохранён для обратной совместимости) |
| Indexer | `src/core/indexer.py` | Сканирование + запись в LanceDB + миграция схем |
| Searcher | `src/core/searcher.py` | Гибридный поиск (BM25 + vector) + Multi-Provider Reranking |
| Reranker | `src/core/reranker.py` | MultiProviderReranker (Ollama → LM Studio → RRF fallback) |
| SymbolIndex | `src/core/symbol_index.py` | Bidirectional Call Graph (BFS depth 2+) + References |
| Parser | `src/core/parser.py` | Tree-sitter AST парсер + extract_calls() |
| RemoteEmbedder | `src/core/remote_embedder.py` | LM Studio / Ollama клиент для эмбеддингов |
| FileGuard | `src/core/file_guard.py` | Фильтрация файлов + gitignore |
| MultiProjectSearcher | `src/core/multi_project_searcher.py` | Кросс-репозиторный поиск (RRF fusion) |
| StructuralSearch | `src/core/structural_search.py` | AST-паттерн поиск (наследование, декораторы, async) |
| MCP Tools | `src/mcp/server.py` | Все 26 MCP-инструментов (create_mcp_server) |

## 5. MCP Tools (26 инструментов)

| # | Tool | Тип | Описание |
|---|------|-----|----------|
| 1 | `search_code(query, mode)` | sync | **Единый поиск:** `auto/fast/quality/deep/context` |
| 2 | `get_index_status()` | sync | Статус индекса: chunks, files, symbols |
| 3 | `get_index_progress()` | sync | Прогресс индексации по проектам |
| 4 | `index_project_dir(path)` | async | Запуск полной индексации проекта |
| 5 | `get_index_timeline()` | sync | История индексации по датам |
| 6 | `index_health(root)` | sync | Диагностика + самовосстановление индекса |
| 7 | `notify_change(path)` | sync | Принудительное обновление индекса файла |
| 8 | `get_symbol_info(query)` | sync | Call Graph: definition + callers + callees |
| 9 | `impact_analysis(symbol)` | sync | Анализ влияния изменения символа |
| 10 | `get_repo_map(root)` | sync | Карта проекта: файлы + символы |
| 11 | `structural_search(pattern)` | sync | Поиск по 13 AST-паттернам |
| 12 | `cross_repo_search(query)` | sync | Поиск по нескольким проектам с `@mention` |
| 13 | `cross_project_deps(action)` | sync | Граф зависимостей между проектами |
| 14 | `watcher_status()` | sync | Статус embedder + LSP компонентов |
| 15 | `get_logs(root)` | sync | Последние ошибки из логов проекта |
| 16 | `get_health_report(root)` | sync | Полная самодиагностика системы |
| 17 | `get_hotspots(root)` | sync | Горячие точки: файлы с высоким баго-рейтом |
| 18 | `get_repo_rank(root, k)` | sync | PageRank важности символов |
| 19 | `get_bug_correlation(root)` | sync | Анализ связи багов с кодом |
| 20 | `get_related_files(root, path)` | sync | Файлы через co-change / bug correlation |
| 21 | `get_commit_history(root)` | sync | Семантическая история коммитов |
| 22 | `get_file_history(root, path)` | sync | История изменений файла |
| 23 | `get_branch_info(root)` | sync | Информация о ветке + статус индекса |
| 24 | `graph_query(type, target)` | sync | Запросы к графу знаний (GraphRAG) |
| 25 | `generate_chunk_summaries(root)` | sync | LLM-описания для чанков кода |
| 26 | `submit_background_task(type)` | async | Фоновые задачи (bug_correlation, graph) |

### Intelligence Layer (10 intel_* tools)

| Tool | Описание |
|------|----------|
| `intel_get_runtime_status()` | Агрегированный статус здоровья рантайма |
| `intel_trigger_reindex()` | Fire-and-forget переиндексация |
| `intel_get_job_status(job_id)` | Прогресс фоновой задачи |
| `intel_code_topology(symbol)` | Граф вызовов + топология модуля |
| `intel_get_project_memory()` | Карта памяти проекта (ADR, issues, debt) |
| `intel_log_incident(...)` | Запись инцидента в историю |
| `intel_analyze_incident(error)` | Поиск аналогичных инцидентов |
| `intel_add_memory_node(...)` | Добавление записи в память проекта |
| `intel_get_hotspots()` | Топ-5 файлов с баго-нагрузкой |
| `intel_predict_root_cause(error)` | Предсказание первопричины сбоя |

### 🔄 Deprecated (← call `search_code` internally)

`smart_search`, `deep_search`, `context_search` — оставлены для обратной совместимости.

## 6. MCP Prompts

| Prompt | Назначение |
|--------|------------|
| `mscodebase-rules` | Системные правила для AI-агента (state-awareness, context budget, safe writing) |

## 7. Установка и конфигурация

Скрипт `install.py` выполняет:

1. Копирование расширения в `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`
2. Создание изолированного venv + установка зависимостей
3. Проверка схемы LanceDB (миграция при необходимости)
4. Настройка MCP + LSP в `settings.json` Zed
5. Настройка `system_prompt` в блоке `agent`
6. Генерация `uninstall.bat`

### Конфигурация в settings.json

```json
{
  "context_servers": {
    "mscodebase-intelligence": {
      "command": "<venv_python>",
      "args": ["<ext_dir>/src/hybrid_server.py"]
    }
  },
  "lsp": {
    "mscodebase-lsp": {
      "command": "<venv_python>",
      "arguments": ["-u", "<ext_dir>/src/hybrid_server.py"]
    }
  },
  "languages": {
    "Python": { "language_servers": ["mscodebase-lsp"] },
    "TypeScript": { "language_servers": ["mscodebase-lsp"] },
    "Rust": { "language_servers": ["mscodebase-lsp"] },
    "Go": { "language_servers": ["mscodebase-lsp"] },
    "JavaScript": { "language_servers": ["mscodebase-lsp"] }
  },
  "agent": {
    "system_prompt": "MSCodeBase Core Rules: ..."
  },
  "mscodebase": {
    "semaphore": { "max_concurrent": 2 },
    "fallback_mode": false
  }
}
```

> **Примечание:** `hybrid_server.py` одновременно обслуживает LSP (stdio) и MCP (HTTP/SSE) — это устраняет конфликты доступа к диску (WinError 5) и обеспечивает чтение из общей памяти процесса.

## 8. Multi-Provider Reranker

Модуль `src/core/reranker.py` реализует интеллектуальный реранкинг через внешние LLM:

### Архитектура

```
[RRF Results] → [MultiProviderReranker.rerank()]
                      │
         ┌────────────┴────────────┐
    (Ollama :11434)         (LM Studio :1234)
         │                         │
  [/api/chat batch]         [/v1/chat/completions batch]
         │                         │
         └────────────┬────────────┘
                      ▼
              [Parse JSON scores]
                      │
                      ▼
              [Sort & return top_n]
```

### Приоритет провайдеров

1. **Ollama** — приоритет, если доступна (специализированные реранкеры `bge-reranker-v2-m3`)
2. **LM Studio** — альтернатива (Instruct-модели типа Qwen2.5-7B-Instruct)
3. **Fallback** — если оба недоступны, возвращается RRF-порядок без изменений

### Безопасность

- Таймаут пинга: 0.5 сек (не блокирует при недоступности)
- Таймаут инференса: 30 сек
- 4-уровневый парсинг JSON (чистый → markdown → regex → отдельные объекты)
- При любой ошибке — прозрачный fallback к RRF

### Пакетная обработка

Все чанки отправляются одним запросом:
- Усечение до 800 символов на чанк
- Строгий JSON-ответ: `{"scores": [{"index": 0, "score": 0.95}, ...]}`
- Один network round-trip независимо от числа чанков

## 9. Call Graph (Граф вызовов)

Модуль `src/core/symbol_index.py` реализует двунаправленный граф вызовов:

### Архитектура

```
[SymbolIndex]
    │
    ├── _definitions: symbol → [SymbolRef]  (кто определён где)
    ├── _references:  symbol → [SymbolRef]  (кто вызывает символ)
    ├── _file_to_defs:   file → {symbols}   (символы в файле)
    └── _file_to_calls:  file → {symbols}   (вызовы в файле)
```

### Алгоритм BFS

```
build_call_graph(symbol, depth=2):
    1. Находим определения символа
    2. BFS вверх (callers): кто вызывает → кто вызывает вызывающих
    3. BFS вниз (callees): кого вызывает → кого вызывает вызываемый
    4. Собираем impact_files (все затронутые файлы)
    5. Формируем call_chain для контекста
```

### Защита от циклов

- Множество `visited_callers` и `visited_callees`
- Ограничение глубины до 5 (автоматически)
- Дедупликация результатов

### Извлечение вызовов

`parser.py` → `extract_calls()`:
- Рекурсивный обход AST
- Идентификация `call_expression`, `function_invocation`
- Поддержка method calls (obj.method()), scoped (module::func)

## 10. Ограничения

- Максимальный размер файла: 1 MB
- Поддерживаемые языки: Python, Rust, TypeScript, JavaScript, Go
- Требуется LM Studio или Ollama для векторного поиска и реранкинга
- Windows native (без Docker/WSL)
- Зависимости: только `httpx` (без onnxruntime/torch/transformers)
- Время: только `zoneinfo`, без `pytz`

---

*Последнее обновление: 2026-06-28*
