<div align="center">

<img src="../../logo/baner.svg" width="800" alt="MSCodeBase Intelligence">

[🇬🇧 English](../en/README.md) • [🇷🇺 Русский](README.md) • [🇨🇳 中文](../zh/README.md)

# MSCodebase Intelligence

**AI-семантический поиск кода для Zed IDE**
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Zed](https://img.shields.io/badge/Zed-extension-orange.svg)](https://zed.dev/)
[![Tests](https://img.shields.io/badge/tests-391%20passing-brightgreen)](tests/)

[Возможности](#-features) • [Быстрый старт](#-quick-start) • [Инструменты](#-mcp-tools-43-total) • [Документация](#-documentation-map) • [Установка](docs/INSTALL.md) • [Архитектура](docs/architecture.md) • [Разработка](CONTRIBUTING.md)

*Последнее обновление: 2026-07-05*

</div>

---

## ✨ Возможности

| Возможность | Описание |
|---------|-------------|
| 🔍 **Унифицированный поиск** | `search_code(query, mode)` — один инструмент для всех типов поиска (fast/quality/deep/context/auto) |
| 🧠 **Интеллектуальный слой** | 10 высокоуровневых `intel_*` инструментов: самодиагностика, топология, предсказание ошибок |
| 🗃️ **Память проекта** | ADR, известные проблемы, технический долг — автоматически сохраняется между сессиями |
| 🌐 **Кросс-репозиторный поиск** | Поиск по нескольким проектам с `@mention` синтаксисом |
| 🌳 **Граф вызовов** | Полный граф вызовов: определение + вызывающие + вызываемые + анализ влияния |
| 🏗 **Структурный поиск** | 13 AST-паттернов (class_inheritance, async_function, decorator и др.) |
| 🔎 **Контекстный поиск** | Найди похожий код — вставь фрагмент, получи семантические дубликаты |
| 💾 **LanceDB v2** | Векторная БД с изоляцией по проектам (инкрементальная BM25 реиндексация) |
| 🛡 **Ограничение скорости** | DebounceBatch + CircuitBreaker — защита от VFS-петель и перегрузок |
| 🏥 **Самодиагностика** | `get_health_report` + `index_health` — полная проверка и восстановление |
| 🧪 **Чистая архитектура** | DI Контейнер (15 сервисов), 43 инструмента (33 class-based + 10 intel), 391+ тестов |
| 🪟 **Мульти-оконность** | `ProjectIndexerRegistry` — изолированный Indexer на проект, LRU 5, ResourceMonitor throttle |

---

## 🚀 Быстрый старт

> Полная инструкция по установке: **[docs/INSTALL.md](docs/INSTALL.md)**

```bash
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence
python install.py
```

**После установки:** File → Quit → открой проект → дождись индексации.

**Проверка:** в Agent Panel (`Ctrl+Shift+P` → `Agent Panel: Toggle`) выполни:
```
get_index_status()
```

> **Windows:** На Windows есть особенности (Restricted Mode, проект резолвится
> через SQLite). Обязательно прочти **[ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md)**
> перед установкой.
>
> **LM Studio:** Рекомендуется для векторного поиска. Установи, запусти
> на порту 1234 — MCP подключится автоматически.

---

## 📚 Карта документации

| Документ | О чём | Для кого |
|----------|-------|----------|
| **[INSTALL.md](INSTALL.md)** | Установка, настройка, удаление | Пользователи |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | Clean Architecture, слои, DI Container | Разработчики |
| **[ARCHITECTURE_LAYERS.md](ARCHITECTURE_LAYERS.md)** | 10 слоёв архитектуры (Filesystem → AI Agent) | Архитекторы |
| **[TELEMETRY.md](TELEMETRY.md)** | Метрики, ETA, сбор данных | DevOps |
| **[LSP_WONTFIX.md](../en/investigations/LSP_WONTFIX.md)** | Расследование: LSP на Windows (WONTFIX) | Поддержка |
| **[ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md)** | Windows-специфика, Restricted Mode, CWD | Все на Windows |
| **[CHANGELOG.md](CHANGELOG.md)** | История версий | Все |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | Как разрабатывать, тестировать, PR | Контрибьюторы |
| **[AGENTS.md](../../AGENTS.md)** | Системные правила для AI-агента (контекст) | AI Agent |
| **[SECURITY.md](SECURITY.md)** | Политика безопасности, уязвимости | Безопасность |

Все документы связаны между собой перекрёстными ссылками. Если заметили расхождение — создайте issue.

---

## 🔧 MCP Инструменты (43 всего)

### Основной поиск

| Инструмент | Когда использовать |
|------|-------------|
| `search_code(query, mode, filter_layer)` | **Главный инструмент поиска.** `mode="auto"` / `"fast"` / `"quality"` / `"deep"` / `"context"`. `filter_layer="core"` — поиск только в указанном архитектурном слое |
| `structural_search(pattern)` | Поиск по AST: `class_inheritance`, `async_function`, `function_with_decorator` и др. |
| `cross_repo_search(query @repo)` | Поиск по нескольким проектам (моно-репо) |
| `cross_project_deps(action)` | Граф зависимостей между проектами: `graph` / `deps` / `cycles` / `impact` |
| `get_symbol_info(query)` | Граф вызовов: кто вызывает, что вызывает, impact-файлы |
| `impact_analysis(symbol)` | Анализ влияния изменения символа (risk score, depth) |

### Управление индексом

| Инструмент | Когда использовать |
|------|-------------|
| `get_index_status()` | Статус индекса: chunks, files, symbols |
| `get_index_progress()` | Прогресс индексации (phase, percent) |
| `index_project_dir(path)` | Запуск полной индексации проекта |
| `get_index_timeline()` | История индексации по датам |
| `index_health(project_root)` | Диагностика и самовосстановление индекса |
| `notify_change(file_path)` | Принудительное обновление индекса файла (через DebounceBatch) |
| `generate_chunk_summaries(root)` | LLM-описания для чанков кода |
| `scan_changes(project_root)` | Архитектурный дифф — анализ изменений относительно последнего baseline |

### Система и диагностика

| Инструмент | Когда использовать |
|------|-------------|
| `get_health_report()` | **Полная самодиагностика:** индекс, embedder, логи, синхронизация |
| `watcher_status()` | Статус компонентов: режим embedder (LM Studio / Ollama / ONNX) |
| `get_logs(project_root)` | Последние ошибки и предупреждения из логов проекта |
| `get_repo_map(project_root)` | Карта проекта: дерево файлов + ключевые символы |
| `read_live_file(path)` | Чтение файла из памяти LSP (включая несохранённые изменения) |

### Аналитика

| Инструмент | Когда использовать |
|------|-------------|
| `get_hotspots(project_root)` | «Горячие точки» — файлы с высоким баго-рейтом |
| `get_repo_rank(project_root, top_k)` | Рейтинг важности символов (PageRank на графе вызовов) |
| `get_bug_correlation(project_root)` | Анализ связи багов с изменениями в коде |
| `get_related_files(project_root, path)` | Файлы, связанные через co-change / bug correlation |
| `graph_query(query_type, target)` | Запросы к графу знаний: `impact` / `feature` / `deps` / `tests` |
| `find_similar_bugs(error)` | Поиск похожих багов из истории по тексту ошибки |

### Git и история

| Инструмент | Когда использовать |
|------|-------------|
| `get_commit_history(root, limit)` | Семантическая история коммитов |
| `get_file_history(root, path)` | История изменений конкретного файла |
| `get_branch_info(project_root)` | Информация о ветке + статус индекса |

### Жизненный цикл и верификация

| Инструмент | Когда использовать |
|------|-------------|
| `submit_background_task(type, root)` | Запуск долгих задач: `bug_correlation` / `build_knowledge_graph` / `full_analysis` |
| `get_task_status(task_id)` | Статус фоновой задачи |
| `verify_action(action_type)` | Верификация: `file_write` / `git_commit` / `git_push` / `index_sync` |
| `predict_eta(operation)` | Предсказание времени выполнения операции |
| `run_health_check()` | Полная проверка здоровья проекта (тесты + git) |

### Интеллектуальный слой (intel_*) — 10 высокоуровневых инструментов

| Инструмент | Что делает |
|------|-------------|
| `intel_get_runtime_status()` | Агрегированный статус здоровья: embedder, index, использование ресурсов |
| `intel_trigger_reindex()` | Fire-and-forget переиндексация (не блокирует Zed) |
| `intel_get_job_status(job_id)` | Прогресс фоновой задачи |
| `intel_code_topology(symbol)` | Граф вызовов + топология модуля (< 2 сек) |
| `intel_get_project_memory()` | Карта памяти проекта: ADR, known_issues, tech_debt |
| `intel_log_incident(...)` | Запись инцидента в историю проекта |
| `intel_analyze_incident(error)` | Поиск аналогичных инцидентов + готовые решения |
| `intel_add_memory_node(section, data)` | Добавление записи в проектную память |
| `intel_get_hotspots()` | Топ-5 файлов с максимальной баго-нагрузкой |
| `intel_predict_root_cause(error)` | Предсказание первопричины сбоя по логам + истории |

---

## 🏗️ Архитектура

### Clean Architecture с DI контейнером

```
┌──────────────────────────────────────────────────────────────────┐
│                   MCP Server (~220 строк)                        │
│            src/mcp/server.py — только регистрация                 │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              DI Контейнер (15 сервисов)                    │   │
│  │  src/core/di_container.py — ServiceCollection              │   │
│  │                                                           │   │
│  │  ┌──────────┐  ┌────────────┐  ┌──────────────────────┐  │   │
│  │  │ Indexer  │  │  Searcher  │  │  DebounceBatch       │  │   │
│  │  │ Embedder │  │  SymbolIdx │  │  CircuitBreaker      │  │   │
│  │  │ Parser   │  │  FileGuard │  │  RateLimiter         │  │   │
│  │  └──────────┘  └────────────┘  └──────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                       │
│              ┌────────────┴────────────┐                         │
│              ▼                          ▼                         │
│  ┌────────────────────┐  ┌────────────────────────────────────┐  │
│  │  33 Класса         │  │  10 intel_* инструментов            │  │
│  │  src/mcp/tools/*.py │  │  src/core/intelligence_layer.py    │  │
│  │  Каждый инструмент  │  │  error_boundary декоратор           │  │
│  │  — отдельный класс │  │  JSON status/message/detail        │  │
│  │  Constructor Inj.   │  │  asyncio.wait_for(timeout)        │  │
│  └────────────────────┘  └────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐     ┌───────────────────┐
│  RemoteEmbedder  │     │  LanceDB v2       │
│  (LM Studio /    │     │  (Векторная БД)    │
│   Ollama / ONNX) │     │  BM25 + Vector    │
└─────────────────┘     └───────────────────┘
```

---

## ⚡ Производительность

| Режим | Задержка | Лучше всего для |
|:-----|:--------|:---------|
| `search_code(query, mode="fast")` | ~300ms | Простой ключевой запрос / точное имя |
| `search_code(query, mode="quality")` | ~1200ms | Семантический поиск с реранкером |
| `search_code(query, mode="deep")` | ~2-5s | Комплексное исследование по модулям |
| `search_code(query, mode="context")` | ~500ms | Поиск похожего кода по фрагменту |
| `cross_repo_search(query @repo)` | ~500ms-2s | Кросс-проектный поиск |

### Переменные окружения

| Переменная | По умолчанию | Описание |
|----------|---------|-------------|
| `LM_STUDIO_URL` | `http://localhost:1234/v1` | API endpoint LM Studio |
| `LM_STUDIO_PORT` | `1234` | Порт LM Studio |
| `OLLAMA_URL` | `http://localhost:11434` | API endpoint Ollama |
| `LOG_LEVEL` | `INFO` | Уровень логирования |
| `ZED_WINDOWS_QUIRKS.md` | *(см. файл)* | Инструкции для Windows |

---

## 🔧 Устранение неполадок

### MCP Сервер не отвечает

**Симптомы:** инструменты не отвечают, таймаут.

**Чеклист:**
1. **File → Quit** → открой проект заново
2. Запустите `python install.py` для перенастройки
3. Проверьте логи: `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`

### Индекс пуст (0 чанков)

В Agent Panel выполните:
```
intel_trigger_reindex()
```

После проверьте: `get_index_status()`

### Проблемы с подключением LM Studio

```bash
# Проверьте, что сервер отвечает:
python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:1234/v1/health').read())"
```

Должен быть ответ `{"status":"ok"}`.

---

## 📁 Структура проекта

```
mscodebase-intelligence/
├── src/
│   ├── main.py                   # Точка входа MCP сервера (~220 строк)
│   ├── lsp_main.py               # LSP сервер (DI-based, для didSave индексации)
│   ├── mcp/
│   │   ├── server.py             # DI маршрутизация — только импорты + регистрация
│   │   └── tools/                 # 10 файлов, 33 class-based + 10 intel = 43 всего
│   │       ├── search_tools.py   # search_code, get_symbol_info, impact_analysis
│   │       ├── indexing_tools.py # notify_change, index_project_dir, index_health
│   │       ├── git_tools.py      # get_branch_info, get_commit_history
│   │       ├── system_tools.py   # get_index_status, watcher_status, read_live_file
│   │       ├── analysis_tools.py # structural_search, get_repo_map, scan_changes
│   │       ├── graph_tools.py    # cross_repo_search, graph_query, get_related_files
│   │       ├── investigation_tools.py  # get_bug_correlation, get_hotspots
│   │       └── lifecycle_tools.py      # submit_background_task, verify_action
│   ├── core/
│   │   ├── di_container.py       # ★ DI Контейнер (15 сервисов, ServiceCollection)
│   │   ├── error_handler.py      # ★ error_boundary + ToolError
│   │   ├── rate_limiter.py       # ★ SlidingWindowRateLimiter + DebounceBatch + CircuitBreaker
│   │   ├── indexer.py            # LanceDB векторное хранилище
│   │   ├── searcher.py           # Гибридный поиск (BM25 + Dense + RRF)
│   │   ├── symbol_index.py       # Граф вызовов (BFS, анализ влияния)
│   │   ├── intelligence_layer.py # intel_* инструменты (10 высокоуровневых)
│   │   ├── remote_embedder.py    # Клиент LM Studio / Ollama
│   │   ├── reranker.py           # Мульти-провайдерный реранкер
│   │   ├── parser.py             # Tree-sitter AST
│   │   ├── health_report.py      # Движок самодиагностики
│   │   └── ...
│   └── utils/
│       ├── paths.py              # SafePathManager, to_win_long_path
│       └── zed_config.py         # Авто-настройка Zed
├── docs/
│   ├── architecture.md
│   └── INSTALL.md
├── tests/                        # 391 тест (pytest)
├── .agents/skills/               # Навыки для AI-агента
├── install.py                    # Установщик
└── README.md
```

---

## 🛠️ Разработка

См. [CONTRIBUTING.md](CONTRIBUTING.md) по следующим темам:
- Как добавлять новые MCP инструменты
- Структура тестов и CI-пайплайн
- Соглашения по сообщениям коммитов

### Быстрый старт для разработчиков

```bash
# Настройка
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Запуск MCP сервера напрямую (тест)
python -m src.main

# Запуск тестов
pytest tests/ -m "not integration and not benchmark"
```

---

## 📄 Лицензия

MIT License — см. [LICENSE](LICENSE) для подробностей.

---

## 🙏 Благодарности

- [Zed IDE](https://zed.dev/) — редактор кода
- [LM Studio](https://lmstudio.ai/) — локальный LLM инференс
- [LanceDB](https://lancedb.github.io/) — векторная база данных
- [Model Context Protocol](https://modelcontextprotocol.io/) — стандарт MCP
