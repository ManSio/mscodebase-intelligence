<div align="center">

# MSCodebase Intelligence

**AI-powered semantic code search for Zed IDE**
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Zed](https://img.shields.io/badge/Zed-extension-orange.svg)](https://zed.dev/)
[![Tests](https://img.shields.io/badge/tests-307%20passing-brightgreen)](tests/)

[Features](#-features) • [Quick Start](#-quick-start) • [Tools](#-mcp-tools-43-total) • [Documentation](#-documentation-map) • [Installation](docs/INSTALL.md) • [Architecture](docs/architecture.md) • [Development](CONTRIBUTING.md)

*Last updated: 2026-07-05*

</div>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔍 **Unified Search** | `search_code(query, mode)` — один инструмент для всех типов поиска (fast/quality/deep/context/auto) |
| 🧠 **Intelligence Layer** | 10 высокоуровневых `intel_*` инструментов: самодиагностика, топология, предсказание ошибок |
| 🗃️ **Project Memory** | ADR, known issues, tech debt — автоматически сохраняется между сессиями |
| 🌐 **Cross-repo Search** | Поиск по нескольким проектам с `@mention` синтаксисом |
| 🌳 **Call Graph** | Полный граф вызовов: definition + callers + callees + impact analysis |
| 🏗 **Structural Search** | 13 AST-паттернов (class_inheritance, async_function, decorator, etc.) |
| 🔎 **Context Search** | Найди похожий код — вставь фрагмент, получи семантические дубликаты |
| 💾 **LanceDB v2** | Векторная БД с изоляцией по проектам (инкрементальная BM25 реиндексация) |
| 🛡 **Rate Limiting** | DebounceBatch + CircuitBreaker — защита от VFS-петель и перегрузок |
| 🏥 **Self-Diagnosis** | `get_health_report` + `index_health` — полная проверка и восстановление |
| 🧪 **Clean Architecture** | DI Container (15 services), 43 tools (33 class-based + 10 intel), 391+ tests |
| 🪟 **Multi-Window** | `ProjectIndexerRegistry` — изолированный Indexer per project, LRU 5, ResourceMonitor throttle |

---

## 🚀 Quick Start

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

## 📚 Documentation Map

| Документ | О чём | Для кого |
|----------|-------|----------|
| **[docs/INSTALL.md](docs/INSTALL.md)** | Установка, настройка, удаление | Пользователи |
| **[docs/architecture.md](docs/architecture.md)** | Clean Architecture, слои, DI Container | Разработчики |
| **[docs/architecture-layers.md](docs/architecture-layers.md)** | 10 слоёв архитектуры (Filesystem → AI Agent) | Архитекторы |
| **[docs/telemetry.md](docs/telemetry.md)** | Метрики, ETA, сбор данных | DevOps |
| **[docs/investigations/2026-07-05-lsp-zed-1.9.0.md](docs/investigations/2026-07-05-lsp-zed-1.9.0.md)** | Расследование: LSP на Windows (WONTFIX) | Поддержка |
| **[ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md)** | Windows-специфика, Restricted Mode, CWD | Все на Windows |
| **[CHANGELOG.md](CHANGELOG.md)** | История версий | Все |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | Как разрабатывать, тестировать, PR | Контрибьюторы |
| **[AGENTS.md](AGENTS.md)** | Системные правила для AI-агента (контекст) | AI Agent |
| **[SECURITY.md](SECURITY.md)** | Политика безопасности, уязвимости | Безопасность |

Все документы связаны между собой перекрёстными ссылками. Если заметили расхождение — создайте issue.

---

## 🔧 MCP Tools (43 total)

### Core Search

| Tool | When to Use |
|------|-------------|
| `search_code(query, mode, filter_layer)` | **Главный инструмент поиска.** `mode="auto"` / `"fast"` / `"quality"` / `"deep"` / `"context"`. `filter_layer="core"` — поиск только в указанном архитектурном слое |
| `structural_search(pattern)` | Поиск по AST: `class_inheritance`, `async_function`, `function_with_decorator` и др. |
| `cross_repo_search(query @repo)` | Поиск по нескольким проектам (моно-репо) |
| `cross_project_deps(action)` | Граф зависимостей между проектами: `graph` / `deps` / `cycles` / `impact` |
| `get_symbol_info(query)` | Call Graph: кто вызывает, что вызывает, impact-файлы |
| `impact_analysis(symbol)` | Анализ влияния изменения символа (risk score, depth) |

### Index Management

| Tool | When to Use |
|------|-------------|
| `get_index_status()` | Статус индекса: chunks, files, symbols |
| `get_index_progress()` | Прогресс индексации (phase, percent) |
| `index_project_dir(path)` | Запуск полной индексации проекта |
| `get_index_timeline()` | История индексации по датам |
| `index_health(project_root)` | Диагностика и самовосстановление индекса |
| `notify_change(file_path)` | Принудительное обновление индекса файла (через DebounceBatch) |
| `generate_chunk_summaries(root)` | LLM-описания для чанков кода |

### System & Diagnostics

| Tool | When to Use |
|------|-------------|
| `get_health_report()` | **Полная самодиагностика:** индекс, embedder, логи, synchronisation |
| `watcher_status()` | Статус компонентов: embedder mode (LM Studio / Ollama / ONNX) |
| `get_logs(project_root)` | Последние ошибки и предупреждения из логов проекта |
| `get_repo_map(project_root)` | Карта проекта: дерево файлов + ключевые символы |
| `read_live_file(path)` | Чтение файла из памяти LSP (включая несохранённые изменения) |

### Analytics

| Tool | When to Use |
|------|-------------|
| `get_hotspots(project_root)` | "Горячие точки" — файлы с высоким баго-рейтом |
| `get_repo_rank(project_root, top_k)` | Рейтинг важности символов (PageRank на графе вызовов) |
| `get_bug_correlation(project_root)` | Анализ связи багов с изменениями в коде |
| `get_related_files(project_root, path)` | Файлы, связанные через co-change / bug correlation |
| `graph_query(query_type, target)` | Запросы к графу знаний: `impact` / `feature` / `deps` / `tests` |
| `find_similar_bugs(error)` | Поиск похожих багов из истории по тексту ошибки |

### Git & History

| Tool | When to Use |
|------|-------------|
| `get_commit_history(root, limit)` | Семантическая история коммитов |
| `get_file_history(root, path)` | История изменений конкретного файла |
| `get_branch_info(project_root)` | Информация о ветке + статус индекса |

### Lifecycle & Verification

| Tool | When to Use |
|------|-------------|
| `submit_background_task(type, root)` | Запуск долгих задач: `bug_correlation` / `build_knowledge_graph` / `full_analysis` |
| `get_task_status(task_id)` | Статус фоновой задачи |
| `verify_action(action_type)` | Верификация: `file_write` / `git_commit` / `git_push` / `index_sync` |
| `predict_eta(operation)` | Предсказание времени выполнения операции |
| `run_health_check()` | Полная проверка здоровья проекта (тесты + git) |

### Intelligence Layer (intel_*) — 10 High-Level Tools

| Tool | What it does |
|------|-------------|
| `intel_get_runtime_status()` | Агрегированный статус здоровья: embedder, index, resource usage |
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

## 🏗️ Architecture

### Clean Architecture with DI Container

```
┌──────────────────────────────────────────────────────────────────┐
│                   MCP Server (~220 lines)                        │
│            src/mcp/server.py — только регистрация                 │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              DI Container (15 services)                   │   │
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
│  │  37 Tool Classes   │  │  10 intel_* tools                  │  │
│  │  src/mcp/tools/*.py │  │  src/core/intelligence_layer.py    │  │
│  │  Каждый инструмент  │  │  error_boundary decorator          │  │
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

## ⚡ Performance

| Mode | Latency | Best For |
|:-----|:--------|:---------|
| `search_code(query, mode="fast")` | ~300ms | Simple keyword / exact name |
| `search_code(query, mode="quality")` | ~1200ms | Semantic search with reranker |
| `search_code(query, mode="deep")` | ~2-5s | Complex research across modules |
| `search_code(query, mode="context")` | ~500ms | Find similar code by fragment |
| `cross_repo_search(query @repo)` | ~500ms-2s | Cross-project search |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LM_STUDIO_URL` | `http://localhost:1234/v1` | LM Studio API endpoint |
| `LM_STUDIO_PORT` | `1234` | LM Studio port |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `ZED_CONFIG_DIR` | *(auto)* | Custom Zed config directory |

---

## 🔧 Troubleshooting

### MCP Server Not Responding

**Symptoms:** `@mscodebase-intelligence` shows "not available" or times out.

**Checklist:**
1. Run `python src/main.py` manually to check for errors
2. Check Zed logs: `%APPDATA%\Zed\logs\Zed.log`
3. Verify `settings.json` has correct `context_servers` entry
4. Run `install.py` again to reconfigure

### Index Empty (0 chunks)

```bash
# Option 1: via MCP tool (in Zed Chat)
index_project_dir(path="your/project/path")

# Option 2: via command line
cd your/project
python -c "from src.core.indexer import Indexer; ..."
```

### LM Studio Connection Issues

```bash
# Test connection
curl http://localhost:1234/v1/embeddings -d '{"input":"test","model":"text-embedding-bge-m3"}'
```

---

## 📁 Project Structure

```
mscodebase-intelligence/
├── src/
│   ├── main.py                   # MCP server entry point (~220 lines)
│   ├── lsp_main.py               # LSP server (DI-based, for didSave indexing)
│   ├── mcp/
│   │   ├── server.py             # DI routing — only imports + registration
│   │   └── tools/                 # 10 files, 37 class-based tools
│   │       ├── search_tools.py   # search_code, get_symbol_info, impact_analysis
│   │       ├── indexing_tools.py # notify_change, index_project_dir, index_health
│   │       ├── git_tools.py      # get_branch_info, get_commit_history
│   │       ├── system_tools.py   # get_index_status, watcher_status, read_live_file
│   │       ├── analysis_tools.py # structural_search, get_repo_map, scan_changes
│   │       ├── graph_tools.py    # cross_repo_search, graph_query, get_related_files
│   │       ├── investigation_tools.py  # get_bug_correlation, get_hotspots
│   │       └── lifecycle_tools.py      # submit_background_task, verify_action
│   ├── core/
│   │   ├── di_container.py       # ★ DI Container (15 services, ServiceCollection)
│   │   ├── error_handler.py      # ★ error_boundary + ToolError
│   │   ├── rate_limiter.py       # ★ SlidingWindowRateLimiter + DebounceBatch + CircuitBreaker
│   │   ├── indexer.py            # LanceDB vector storage
│   │   ├── searcher.py           # Hybrid search (BM25 + Dense + RRF)
│   │   ├── symbol_index.py       # Call Graph (BFS, impact analysis)
│   │   ├── intelligence_layer.py # intel_* tools (10 high-level)
│   │   ├── remote_embedder.py    # LM Studio / Ollama client
│   │   ├── reranker.py           # Multi-Provider Reranker
│   │   ├── parser.py             # Tree-sitter AST
│   │   ├── health_report.py      # Self-diagnosis engine
│   │   └── ...
│   └── utils/
│       ├── paths.py              # SafePathManager, to_win_long_path
│       └── zed_config.py         # Auto-configure Zed settings
├── docs/
│   ├── ARCHITECTURE.md
│   └── INSTALL.md
├── tests/                        # 325 tests (52 new — DI/RateLimiter/ErrorHandler)
├── .agents/skills/               # Skills for AI agent
├── install.py                    # Installer
└── README.md
```

---

## 🛠️ Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for:
- How to add new MCP tools
- Test structure and CI pipeline
- Commit message conventions

### Quick Start for Devs

```bash
# Setup
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Run MCP server directly (test)
python -m src.main

# Run tests
pytest tests/ -m "not integration and not benchmark"
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- [Zed IDE](https://zed.dev/) — code editor
- [LM Studio](https://lmstudio.ai/) — local LLM inference
- [LanceDB](https://lancedb.github.io/) — vector database
- [Model Context Protocol](https://modelcontextprotocol.io/) — MCP standard
