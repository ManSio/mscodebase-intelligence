<div align="center">

# MSCodebase Intelligence

**AI-powered semantic code search for Zed IDE**
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Zed](https://img.shields.io/badge/Zed-extension-orange.svg)](https://zed.dev/)

[Features](#-features) • [Quick Start](#-quick-start) • [Tools](#-mcp-tools) • [Installation](docs/INSTALL.md) • [Architecture](docs/architecture.md) • [Development](#-development)

*Last updated: 2026-07-03*

</div>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔍 **Unified Search** | `search_code(query, mode)` — один инструмент для всех типов поиска (fast/quality/deep/context) |
| 🧠 **Intelligence Layer** | 10 высокоуровневых `intel_*` инструментов: самодиагностика, топология, предсказание ошибок |
| 🗃️ **Project Memory** | ADR, known issues, tech debt — автоматически сохраняется между сессиями |
| 🌐 **Cross-repo Search** | Поиск по нескольким проектам с `@mention` синтаксисом |
| 🌳 **Call Graph** | Полный граф вызовов: definition + callers + callees + impact analysis |
| 🏗 **Structural Search** | 13 AST-паттернов (class_inheritance, async_function, decorator, etc.) |
| 🔎 **Context Search** | Найди похожий код — вставь фрагмент, получи семантические дубликаты |
| 🔌 **LSP + MCP Hybrid** | Единый процесс: LSP для индексации, MCP для AI-инструментов |
| 💾 **LanceDB v2** | Векторная БД с изоляцией по проектам |
| 🧠 **In-Memory Indexing** | Чтение из LSP VFS — без задержек диска на Windows |
| 🏥 **Self-Diagnosis** | `get_health_report` + `index_health` — полная проверка и восстановление |

---

## 🚀 Quick Start

> Полная инструкция по установке: **[docs/INSTALL.md](docs/INSTALL.md)**

```bash
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence
python install.py
```

Перезапусти Zed → открой Agent Panel (`Ctrl+Shift+P` → `Agent Panel: Toggle`) →
задай вопрос вроде `"найди все файлы отвечающие за индексацию"`.

> **LM Studio (опционально):** Установи LM Studio для более быстрых эмбеддингов.
> Без LM Studio расширение использует встроенный ONNX-эмбеддер (работает офлайн).

---

## 🔧 MCP Tools (36 total)

### Core Search

| Tool | When to Use |
|------|-------------|
| `search_code(query, mode)` | **Главный инструмент поиска.** `mode="auto"` (по умолч.) / `"fast"` / `"quality"` / `"deep"` / `"context"` |
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
| `notify_change(file_path)` | Принудительное обновление индекса файла |
| `generate_chunk_summaries(root)` | LLM-описания для чанков кода |

### System & Diagnostics

| Tool | When to Use |
|------|-------------|
| `get_health_report()` | **Полная самодиагностика:** индекс, embedder, логи, synchronisation |
| `watcher_status()` | Статус компонентов: embedder mode (LM Studio / Ollama / ONNX) |
| `get_logs(project_root)` | Последние ошибки и предупреждения из логов проекта |
| `get_repo_map(project_root)` | Карта проекта: дерево файлов + ключевые символы |

### Analytics

| Tool | When to Use |
|------|-------------|
| `get_hotspots(project_root)` | "Горячие точки" — файлы с высоким баго-рейтом |
| `get_repo_rank(project_root, top_k)` | Рейтинг важности символов (PageRank на графе вызовов) |
| `get_bug_correlation(project_root)` | Анализ связи багов с изменениями в коде |
| `get_related_files(project_root, path)` | Файлы, связанные через co-change / bug correlation |
| `graph_query(query_type, target)` | Запросы к графу знаний: `impact` / `feature` / `deps` / `tests` |

### Git & History

| Tool | When to Use |
|------|-------------|
| `get_commit_history(root, limit)` | Семантическая история коммитов |
| `get_file_history(root, path)` | История изменений конкретного файла |
| `get_branch_info(project_root)` | Информация о ветке + статус индекса |

### Background Tasks

| Tool | When to Use |
|------|-------------|
| `submit_background_task(type, root)` | Запуск долгих задач: `bug_correlation` / `build_knowledge_graph` / `full_analysis` |
| `get_task_status(task_id)` | Статус фоновой задачи |

### 🔄 Deprecated (← call `search_code` internally)

`smart_search`, `deep_search`, `context_search` — оставлены для обратной совместимости.
Используйте `search_code(query, mode="quality"|"deep"|"context")` вместо них.

---

### Intelligence Layer (intel_* tools) — 10 High-Level Tools

Эти инструменты — **"мозг" над MCP**. Они агрегируют данные из нескольких низкоуровневых вызовов.

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

### Dual-Server Architecture (MCP-only, no LSP in this server)

```
┌─────────────────────────────────────────────────────────────┐
│               MCP Server (src/mcp/server.py)                 │
│                                                             │
│  Provides 26 MCP tools for AI assistants via                │
│  @mscodebase-intelligence in Zed Chat                       │
│                                                             │
│  ┌──────────────────┐  ┌────────────────────────────────┐   │
│  │  Core Engine      │  │  Intelligence Layer (intel_*)  │   │
│  │  ─────────────    │  │  ──────────────────────────    │   │
│  │  • Indexer        │  │  • Runtime Status             │   │
│  │  • Searcher       │  │  • Project Memory             │   │
│  │  • SymbolIndex    │  │  • Root Cause Prediction      │   │
│  │  • RemoteEmbedder │  │  • Topology Analysis          │   │
│  │  • Reranker       │  │  • Incident Logging           │   │
│  └──────────────────┘  └────────────────────────────────┘   │
│                            │                                  │
│                      ┌─────▼──────┐                          │
│                      │  LanceDB   │                          │
│                      │  (Vector)  │                          │
│                      └────────────┘                          │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│  RemoteEmbedder │
│  (LM Studio)    │
└─────────────────┘
```

### Storage

Vector indexes are isolated per project:
```
<PROJECT_ROOT>/.codebase_indices/lancedb_v2/index_<project>_<hash>.db
```

### Multi-Provider Reranking

After RRF fusion, results can be reranked by an external LLM:

```
[Recall (BM25 + Dense)] → [Top-20 RRF] → [MultiProviderReranker]
                                                │
                    ┌───────────────────────────┴───────────────────────────┐
              (Ollama available?)                                 (LM Studio available?)
                    │                                                     │
          [Ollama /api/chat batch]                            [LM Studio /v1/chat batch]
                    │                                                     │
                    └───────────────────────────┬───────────────────────────┘
                                                ▼
                                      [Sort by LLM scores] → [ZED Chat]
```

> For full architecture details, see [docs/architecture.md](docs/architecture.md).

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
│   ├── main.py                   # MCP server entry point
│   ├── mcp/
│   │   └── server.py             # All 26 MCP tools (create_mcp_server)
│   ├── core/
│   │   ├── indexer.py            # LanceDB vector storage
│   │   ├── searcher.py           # Hybrid search (BM25 + Dense + RRF)
│   │   ├── symbol_index.py       # Call Graph (BFS, impact analysis)
│   │   ├── intelligence_layer.py # intel_* tools
│   │   ├── remote_embedder.py    # LM Studio / Ollama client
│   │   ├── reranker.py           # Multi-Provider Reranker
│   │   ├── parser.py             # Tree-sitter AST
│   │   ├── health_report.py      # Self-diagnosis engine
│   │   ├── index_guard.py        # Index repair & migration
│   │   └── ...
│   └── utils/
│       └── zed_config.py         # Auto-configure Zed settings
├── docs/
│   ├── architecture.md
│   └── windows-setup.md
├── tests/                        # 312 tests
├── .agents/skills/               # Skills for AI agent
├── install.py                    # Installer
├── sync_to_installed.bat         # Sync source → installed extension
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
