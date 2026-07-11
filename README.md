# MSCodebase Intelligence

**MCP-сервер для семантического поиска кода в Zed IDE.**

[🇬🇧 English](README.md) • [🇷🇺 Русский](docs/ru/README.md) • [🇨🇳 中文](docs/zh/README.md)

[Features](#features) • [Quick Start](#quick-start) • [Tools](#mcp-tools-50-total) • [Documentation](#documentation-map) • [Architecture](docs/en/ARCHITECTURE.md)

*Last updated: 2026-07-11*

---

## Features

| Возможность | Описание |
|-------------|---------|
| **Поиск кода** | `search_code()` — BM25 + векторный + RRF + реранкер. 5 режимов: fast/quality/deep/context/ask |
| **Граф вызовов** | `get_symbol_info()` + `impact_analysis()` — кто вызывает, кого вызывает, риск изменений |
| **Память проекта** | ADR, known issues, tech debt — сохраняются между сессиями |
| **Диагностика** | `intel_get_runtime_status()` — состояние эмбеддера, индекса, ресурсов |
| **Поиск по репозиториям** | `cross_repo_search()` — поиск по нескольким проектам |

**50 MCP-инструментов:** 33 core + 14 intel + 3 diagnostic.

---

## Quick Start

Установи расширение `mscodebase-intelligence` в Zed, затем:

```bash
# Скопировать исходники в расширение
cd D:\Project\MSCodeBase
python install.py

# Перезагрузить Zed (File → Quit → reopen)
# После перезапуска проверить:
#   intel_get_runtime_status()
```

**install.py делает:**
1. Копирует 39+ файлов исходников в директорию расширения
2. Устанавливает Python-зависимости
3. Скачивает llama-server.exe + GGUF модели (bge-m3 embed + reranker)
4. Настраивает MCP в settings.json Zed

Подробнее: [AI_INSTALLATION_PROMPT.md](AI_INSTALLATION_PROMPT.md), [docs/en/INSTALL.md](docs/en/INSTALL.md)

### Провайдеры

MCP сам выбирает лучший доступный:

```
llama.cpp GGUF (GPU) → ONNX Runtime (CPU) → LM Studio (если запущен) → BM25 only
   ~1.0 GB RAM           ~1.7 GB RAM          ~6 GB RAM             без эмбеддингов
   2× llama-server       in-process ONNX       внешний API
```

Бенчмарки: [docs/research/2026-07-10-final-benchmark.md](docs/research/2026-07-10-final-benchmark.md)

---

## Documentation Map

| Документ | Для кого |
|----------|----------|
| [INSTALL.md](docs/en/INSTALL.md) | Установка, настройка |
| [ARCHITECTURE.md](docs/en/ARCHITECTURE.md) | Архитектура, DI, слои |
| [SEARCH_PIPELINE.md](docs/en/SEARCH_PIPELINE.md) | Пайплайн поиска |
| [GRACEFUL_DEGRADATION.md](docs/en/GRACEFUL_DEGRADATION.md) | 5 уровней деградации |
| [FAQ.md](docs/en/FAQ.md) | Частые вопросы |
| [ZED_WINDOWS_QUIRKS.md](docs/en/ZED_WINDOWS_QUIRKS.md) | Особенности Windows |
| [CHANGELOG.md](docs/en/CHANGELOG.md) | История версий |
| [KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | Известные проблемы |
| [CONTRIBUTING.md](docs/en/CONTRIBUTING.md) | Для разработчиков |

Все документы на 3 языках: English, Русский, 中文.

---

## MCP Tools (50 total)

### Core Search (6)
`search_code()` — главный инструмент поиска. Параметры:
- `mode`: auto / fast / quality / deep / context / ask
- `intent_hint`: code / docs / auto
- `filter_layer`: core / mcp / utils / tests

`get_symbol_info()`, `impact_analysis()`, `structural_search()`,
`cross_repo_search()`, `cross_project_deps()`

### Index Management (8)
`get_index_status()`, `index_project_dir()`, `notify_change()`,
`get_index_progress()`, `get_index_timeline()`, `index_health()`,
`generate_chunk_summaries()`, `scan_changes()`

### System & Diagnostics (5)
`get_health_report()`, `watcher_status()`, `get_logs()`,
`get_repo_map()`, `read_live_file()`

### Analytics (6)
`get_hotspots()`, `get_repo_rank()`, `get_bug_correlation()`,
`get_related_files()`, `graph_query()`, `find_similar_bugs()`

### Git & History (3)
`get_commit_history()`, `get_file_history()`, `get_branch_info()`

### Lifecycle (3)
`submit_background_task()`, `get_task_status()`, `verify_action()`

### Intelligence Layer — 14 intel_* tools
`intel_get_runtime_status()`, `intel_trigger_reindex()`,
`intel_get_job_status()`, `intel_code_topology()`,
`intel_get_project_memory()`, `intel_log_incident()`,
`intel_analyze_incident()`, `intel_add_memory_node()`,
`intel_get_hotspots()`, `intel_predict_root_cause()`,
`intel_get_telemetry()`, `intel_tool_health()`,
`intel_execution_timeline()`, `intel_explain_project_state()`

### Diagnostic (3)
`debug_runtime_passport()`, `get_runtime_counters()`,
`intel_execution_timeline()`

---

## Performance

| Режим | Латенси | Когда использовать |
|-------|---------|-------------------|
| `search_code(mode="fast")` | ~300ms | Точное имя/термин |
| `search_code(mode="quality")` | ~1200ms | Семантический поиск |
| `search_code(mode="deep")` | ~5-15s | Сложный запрос |
| `search_code(mode="context")` | ~500ms | Поиск по фрагменту |
| `get_index_status()` | ~50ms | Статус индекса |
| `intel_get_runtime_status()` | ~200ms | Агрегированный статус |

---

## Project Structure

```
mscodebase-intelligence/
├── src/              # 2.2 MB — исходный код MCP
│   ├── main.py       # Точка входа
│   ├── mcp/
│   │   ├── server.py # DI-контейнер, регистрация инструментов
│   │   └── tools/    # 33 core инструмента
│   ├── core/         # Бизнес-логика
│   │   ├── indexer.py, searcher.py, llama_runner.py, ...
│   │   └── intelligence_layer.py  # 14 intel инструментов
│   └── utils/
├── docs/             # 61 .md (en/ru/zh)
├── tests/            # 396 тестов (pytest)
├── install.py        # Установщик
└── README.md
```

---

## Development

```bash
# Запуск MCP напрямую (для отладки)
cd "%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence"
venv\Scripts\python.exe -m src.main

# Тесты
pytest tests/
```

Подробнее: [CONTRIBUTING.md](docs/en/CONTRIBUTING.md), [AGENTS.md](AGENTS.md) (правила для AI-агента)

---

## License

MIT — см. [LICENSE](LICENSE).
