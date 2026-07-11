# MSCodebase Intelligence

**MCP-сервер для семантического поиска кода в Zed IDE.**

[🇬🇧 English](../../README.md) • [🇷🇺 Русский](README.md) • [🇨🇳 中文](../zh/README.md)

[Возможности](#возможности) • [Быстрый старт](#быстрый-старт) • [Инструменты](#mcp-инструменты-50-всего) • [Документация](#карта-документации)

*Последнее обновление: 2026-07-11*

---

## Возможности

| Возможность | Описание |
|-------------|---------|
| **Поиск кода** | `search_code()` — BM25 + векторный + RRF + реранкер. 5 режимов |
| **Граф вызовов** | `get_symbol_info()` + `impact_analysis()` |
| **Память проекта** | ADR, known issues, tech debt |
| **Диагностика** | `intel_get_runtime_status()` — состояние эмбеддера, индекса, ресурсов |
| **Поиск по репозиториям** | `cross_repo_search()` |

**50 MCP-инструментов:** 33 core + 14 intel + 3 diagnostic.

---

## Быстрый старт

Установи расширение `mscodebase-intelligence` в Zed, затем:

```bash
cd D:\Project\MSCodeBase
python install.py

# Перезагрузить Zed (File → Quit → reopen)
```

**install.py делает:**
1. Копирует 39+ файлов исходников в расширение
2. Устанавливает Python-зависимости
3. Скачивает llama-server.exe + GGUF модели
4. Настраивает MCP в settings.json Zed

Подробнее: [INSTALL.md](INSTALL.md), [AI_INSTALLATION_PROMPT.md](../../AI_INSTALLATION_PROMPT.md)

---

## Карта документации

| Документ | Описание |
|----------|----------|
| [INSTALL.md](INSTALL.md) | Установка, настройка |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Архитектура, DI, слои |
| [FAQ.md](FAQ.md) | Частые вопросы |
| [ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md) | Особенности Windows |
| [CHANGELOG.md](CHANGELOG.md) | История версий |
| [KNOWN_ISSUES.md](../../docs/KNOWN_ISSUES.md) | Известные проблемы |

---

## MCP Инструменты (50 всего)

### Поиск (6)
`search_code(mode=auto/fast/quality/deep/context/ask, intent_hint=code/docs/auto)`,
`get_symbol_info()`, `impact_analysis()`, `structural_search()`,
`cross_repo_search()`, `cross_project_deps()`

### Индексация (8)
`get_index_status()`, `index_project_dir()`, `notify_change()`,
`get_index_progress()`, `get_index_timeline()`, `index_health()`,
`generate_chunk_summaries()`, `scan_changes()`

### Система и диагностика (5)
`get_health_report()`, `watcher_status()`, `get_logs()`,
`get_repo_map()`, `read_live_file()`

### Аналитика (6)
`get_hotspots()`, `get_repo_rank()`, `get_bug_correlation()`,
`get_related_files()`, `graph_query()`, `find_similar_bugs()`

### Git (3)
`get_commit_history()`, `get_file_history()`, `get_branch_info()`

### Жизненный цикл (3)
`submit_background_task()`, `get_task_status()`, `verify_action()`

### Интеллектуальный слой — 14 intel_* инструментов
`intel_get_runtime_status()`, `intel_trigger_reindex()`,
`intel_get_job_status()`, `intel_code_topology()`,
`intel_get_project_memory()`, `intel_log_incident()`,
`intel_analyze_incident()`, `intel_add_memory_node()`,
`intel_get_hotspots()`, `intel_predict_root_cause()`,
`intel_get_telemetry()`, `intel_tool_health()`,
`intel_execution_timeline()`, `intel_explain_project_state()`

### Диагностические (3)
`debug_runtime_passport()`, `get_runtime_counters()`,
`intel_execution_timeline()`

---

## Структура проекта

```
mscodebase-intelligence/
├── src/              # Исходный код MCP
│   ├── main.py       # Точка входа
│   ├── mcp/          # Сервер + 33 core инструмента
│   ├── core/         # Бизнес-логика + 14 intel инструментов
│   └── utils/
├── docs/             # 61 .md файл (en/ru/zh)
├── tests/            # 396 тестов
└── install.py        # Установщик
```
