<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](../en/CONTRIBUTING.md) • [🇷🇺 Русский](CONTRIBUTING.md) • [🇨🇳 中文](../zh/CONTRIBUTING.md)

# Контрибьюция — MSCodeBase Intelligence

> **Версия:** 3.3.9 — DocSync Edition

---

## 1. Настройка

```powershell
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd MSCodeBase
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e "."
```

Требования: Python 3.10+, Windows (основная) или Linux (экспериментально).

---

## 2. Архитектура (Clean Architecture)

```
src/
├── main.py              # Точка входа (минимальная)
├── mcp/
│   ├── server.py        # Регистрация MCP-сервера (~220 строк)
│   ├── server_factory.py # Фабрика сервера + DI setup
│   ├── server_tools.py  # Регистрация инструментов (всего 48)
│   └── tools/           # 14 файлов, 19 core + 13 intel + 12 inline + 4 dev
│       ├── base.py          # MCPTool ABC
│       ├── search_tools.py  # search_code, get_symbol_info, impact_analysis
│       ├── codebase_tool.py # codebase(action={rename,move,delete,...})
│       ├── write_tools.py   # write(action={rename,move,delete,replace,insert,impact})
│       ├── graph_tools.py   # graph_query, cross_repo_search, cross_project_deps
│       ├── indexing_tools.py# управление индексом
│       ├── git_tools.py     # git(action={log,history,branch})
│       ├── doc_tools.py     # generate_docs, bump_version, auto_update_docs, install_git_hooks
│       ├── dev_tools.py     # dev-инструменты
│       ├── system_tools.py  # system/health инструменты
│       ├── analysis_tools.py# structural_search, scan_changes и др.
│       ├── investigation_tools.py # bug_correlation, hotspots и др.
│       ├── lifecycle_tools.py# фоновые задачи, верификация
│       └── meta_tools.py    # статус индекса, health-отчёты
├── core/                # Чистая бизнес-логика (БЕЗ импортов MCP)
│   ├── di_container.py  # ServiceCollection (15+ сервисов)
│   ├── error_handler.py # error_boundary + ToolError
│   ├── rate_limiter.py  # SlidingWindowRateLimiter + CircuitBreaker
│   ├── runtime_coordinator.py # ExecutionVerdict + can_execute()
│   ├── graph.py         # PropertyGraph (SQLite WAL) — nodes/edges
│   ├── doc_sync_engine.py # Авто-синхронизация доков с кодом (rename hook)
│   ├── search/
│   │   ├── engine.py    # Гибридный поиск (BM25 + Dense + FTS5 + RRF)
│   │   ├── fts5_mixin.py# FTS5 полнотекстовый поиск
│   │   ├── graph_adapter.py # PropertyGraph → SymbolIndex
│   │   ├── cypher_engine.py # Cypher→SQL
│   │   └── scoring.py   # RRF + MMR diversity
│   ├── indexing/
│   │   ├── indexer.py   # LanceDB векторное хранилище
│   │   ├── db_manager.py# Жизненный цикл LanceDB (PID-lock)
│   │   ├── parser.py    # Tree-sitter AST (16 языков)
│   │   ├── file_guard.py# .gitignore + фильтр расширений
│   │   ├── symbol_index.py # Граф вызовов (BFS, PageRank)
│   │   └── watchdog.py  # Вотчер изменений файлов
│   └── intelligence/
│       ├── layer.py     # 13 intel_* инструментов
│       ├── project_context.py # Снэпшот состояния проекта
│       ├── health.py    # Проверки здоровья системы
│       └── tools_reg.py # Регистрация Intel-инструментов
├── providers/
│   ├── embedder/
│   │   └── remote_embedder.py # ONNX E5-small + LM Studio/Ollama
│   └── reranker/
│       ├── llama_runner.py   # Жизненный цикл llama-server.exe
│       ├── multi_provider.py # Мульти-провайдерный реранкинг
│       └── search_result_reranker.py # Реранкинг результатов
└── utils/
    ├── i18n.py          # Интернационализация
    ├── paths.py         # SafePathManager
    └── zed_config.py    # Управление настройками Zed
```

**Ключевые принципы:**
1. Все инструменты — отдельные классы с Constructor Injection (через `MCPTool`)
2. Каждый инструмент задекорирован `@error_boundary` (JSON + таймаут)
3. Единый DI-контейнер — `create_service_collection()` в `di_container.py`
4. Слой Core имеет НОЛЬ импортов MCP

---

## 3. Стиль кода

- **Форматтер**: Black (длина строки 88)
- **Порядок импортов**: isort
- **Type hints**: обязательны для всех публичных API
- **Логирование**: `logging.getLogger(__name__)` — никогда `print()` в production-коде
- **Async**: используйте `async/await` для I/O; тяжёлые дисковые операции → `asyncio.to_thread()`

```powershell
# Проверка форматирования
black --check src/
isort --check-only src/

# Авто-форматирование
black src/
isort src/
```

---

## 4. Запуск тестов

В проекте **565+ тестов** в `tests/`.

```powershell
# Полный набор
pytest tests/ -v

# Только быстрые тесты (без slow/integration/benchmark)
pytest tests/ -v -m "not slow and not integration and not benchmark"

# По маркеру
pytest tests/ -v -m slow
pytest tests/ -v -m integration
pytest tests/ -v -m benchmark

# По модулю
pytest tests/test_engine.py -v
pytest tests/test_parser.py -v

# С покрытием
pytest tests/ --cov=src --cov-report=term-missing
```

**Маркеры** (определены в `pyproject.toml`):
- `slow` — медленные тесты
- `integration` — интеграционные тесты (требуют LanceDB)
- `benchmark` — бенчмарки производительности
- `asyncio` — async-тесты

### Категории тестов

| Категория | Количество | Описание |
|----------|-------|-------------|
| Unit | 550+ | Без внешних сервисов, <5с каждый |
| Integration | 3 | Требуют LanceDB, маркированы `@pytest.mark.integration` |
| Benchmark | 6 | Замеры latency/throughput |

### CI-пайплайн

```bash
# Минимальный (каждый коммит)
pytest tests/ -m "not integration and not benchmark" --tb=short -q

# Полный (ночной прогон)
pytest tests/ --tb=long -v
```

---

## 5. Добавление новых MCP-инструментов

Инструменты регистрируются в `src/mcp/server_tools.py` через `register_all_tools()`.
Каждый инструмент — класс в `src/mcp/tools/*.py`, наследующий от `MCPTool`.

### Категории инструментов (всего 48):

| Категория | Количество | Ключевые инструменты |
|----------|-------|-----------|
| **Search** | 3 | `search_code`, `get_symbol_info`, `impact_analysis` |
| **Codebase** | 1 | `codebase(action=rename/move/delete/...)` |
| **Write** | 1 | `write(action=rename/move/delete/replace/insert)` |
| **Analysis** | 5 | `structural_search`, `get_repo_map`, `scan_changes` и др. |
| **Graph** | 3 | `graph_query`, `cross_repo_search`, `cross_project_deps` |
| **Git** | 1 | `git(action=log/history/branch)` |
| **Indexing** | 1 | `get_index_status`, `notify_change`, `watcher_status` |
| **Docs** | 1 | `generate_docs`, `bump_version`, `auto_update_docs`, `install_git_hooks` |
| **Investigation** | 3 | `get_bug_correlation`, `get_hotspots`, `find_similar_bugs` |
| **Lifecycle** | 3 | `submit_background_task`, `get_task_status`, `verify_action` |
| **System** | 1 | `read_live_file`, `get_health_report`, `get_logs` |
| **Meta** | 1 | статус индекса, health-отчёты |
| **Intelligence** | 13 | `intel_get_runtime_status`, `intel_trigger_reindex` и др. |
| **Dev** | 3 | `generate_docs`, `bump_version`, `install_git_hooks` |
| **Diagnostic inline** | 12 | `debug_runtime_passport`, `intel_get_project_context`, `intel_explain_project_state`, `get_runtime_counters`, `intel_tool_health`, `intel_execution_timeline`, `refresh_db_connection`, `notify_change`, `read_live_file`, `get_logs`, `get_health_report`, `ack_impact` |

### Шаги для добавления нового инструмента:

1. **Создайте класс** в `src/mcp/tools/<category>.py`:

```python
from src.core.di_container import ServiceCollection
from src.mcp.tools.base import MCPTool
from src.core.error_handler import error_boundary


class MyNewTool(MCPTool):
    """Описание для AI-агента.

    ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
    - Сценарий использования 1
    - Сценарий использования 2

    Args:
        param: Описание параметра
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="my_new_tool")

    @error_boundary("my_new_tool", timeout_ms=15000)
    async def execute(self, param: str, **kwargs) -> dict:
        # Реализация
        return {"status": "ok", "result": param}
```

2. **Зарегистрируйте** в `src/mcp/server_tools.py`:

```python
from src.mcp.tools.my_module import MyNewTool

def register_all_tools(mcp, services):
    tool_classes = [
        ...
        MyNewTool,
    ]
    for cls in tool_classes:
        tool = cls(services)
        mcp.tool()(tool.execute)
```

3. **Добавьте тесты** в `tests/test_<module>.py`.

4. **Обновите документацию**:
   - `README.md` — секция Tools
   - `ARCHITECTURE.md` — если изменилась архитектура
   - `CHANGELOG.md` — добавьте запись

5. **Запустите проверку**:

```powershell
python -m pytest tests/ -q --tb=short
auto_update_docs(action="verify")
```

---

## 6. Добавление новых модулей ядра

Модули ядра находятся в `src/core/`. Импорты MCP запрещены.

### Шаги:

1. **Создайте файл** в соответствующей поддиректории `src/core/`:

```python
"""Модуль для ..."""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MyModule:
    def __init__(self, ...):
        ...

    def do_something(self) -> Any:
        """Что делает метод."""
        ...
```

2. **Зарегистрируйте в DI** в `src/core/di_container.py`:

```python
services.add_singleton(MyModule, MyModule(...))
```

3. **Добавьте тесты** в `tests/test_my_module.py`.

4. **Обновите ARCHITECTURE.md**.

5. **Запустите DocSync** для проверки соответствия документации:

```python
from src.core.doc_sync_engine import DocSyncEngine
engine = DocSyncEngine(project_root)
report = engine.sync_all()
```

---

## 7. Commit Messages

Conventional Commits: `type(scope): description`

**Типы:** `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`

**Scopes:** `search`, `indexer`, `parser`, `mcp`, `core`, `tests`, `docs`, `doc_sync`

**Примеры:**
```
feat(search): add FTS5 full-text search to hybrid pipeline
fix(indexer): handle LanceDB Not found during reindex
docs: update ARCHITECTURE.md with DocSync engine
refactor(doc_sync): clean up suggestion logic
```

---

## 8. Процесс PR

### Чек-лист:

- [ ] Ветка создана от `development` (не `main`)
- [ ] `pytest tests/ -v` — все тесты проходят
- [ ] `black --check src/` — форматирование OK
- [ ] Type hints на всех публичных функциях
- [ ] Нет `print()` в production-коде (используйте `logging`)
- [ ] Новые инструменты/модули покрыты тестами
- [ ] `CHANGELOG.md` обновлён
- [ ] `README.md` обновлён (если изменился публичный API)
- [ ] `ARCHITECTURE.md` обновлён (если изменилась архитектура)
- [ ] DocSync проверка: `auto_update_docs(action="verify")`

### Описание PR должно содержать:

1. **Что изменено** — конкретные файлы и функции
2. **Зачем** — какую проблему решает
3. **Как протестировано** — какие тесты добавлены/прогнаны
4. **Breaking changes** — если есть, явно указать

---

## 9. Версионирование

SemVer: MAJOR.MINOR.PATCH

- **MAJOR** — несовместимые изменения API
- **MINOR** — новые инструменты/функции (обратно совместимые)
- **PATCH** — багфиксы

Текущая версия в `pyproject.toml`: `3.3.9`

---

## 10. Troubleshooting

| Проблема | Решение |
|---------|----------|
| `ModuleNotFoundError: No module named 'src'` | Запускайте из корня проекта |
| Тесты падают с ошибкой эмбеддинга | Нормально для fallback-режима; запустите с LM Studio для полного тестирования |
| MCP-сервер таймаутит при первом вызове | Холодный старт реранкера — второй вызов работает |
| DocSync сообщает о ложных расхождениях | Запустите `auto_update_docs(action="verify")` для текущего состояния |

---

*Последнее обновление: 2026-07-21 | DocSync Edition*
