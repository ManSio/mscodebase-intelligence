<img src="logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

# Contributing — MSCodeBase Intelligence

[🇬🇧 English](CONTRIBUTING.md) • [🇷🇺 Русский](CONTRIBUTING.ru.md) • [🇨🇳 中文](CONTRIBUTING.zh.md)

Гайд для контрибьюторов. Версия проекта: **2.4.x** (Clean Architecture с DI).

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

Требования: Python 3.10+, LM Studio (опционально, для эмбеддингов).

---

## 2. Архитектура (Clean Architecture)

```
src/
├── main.py              # Точка входа (минимальная)
├── lsp_main.py          # LSP handler (DI через ServiceCollection)
├── mcp/
│   ├── server.py        # ~220 строк — только регистрация инструментов
│   └── tools/           # 10 файлов, 43 инструмента (33 class-based + 10 intel)
│       ├── base.py          # MCPTool ABC
│       ├── search_tools.py  # 3 search tools
│       ├── indexing_tools.py# 3 indexing tools
│       ├── git_tools.py     # 3 git tools
│       ├── system_tools.py  # 9 system tools
│       ├── analysis_tools.py# 5 analysis tools
│       └── ...
├── core/                # Бизнес-логика (без MCP-зависимостей)
│   ├── di_container.py  # ServiceCollection (15 services)
│   ├── error_handler.py # error_boundary + ToolError
│   ├── rate_limiter.py  # DebounceBatch + CircuitBreaker
│   ├── indexer.py
│   ├── searcher.py
│   └── ...
└── utils/
    ├── paths.py         # SafePathManager
    └── zed_config.py    # ZedSettings
```

**Ключевые принципы:**
1. Все инструменты — отдельные классы с Constructor Injection (через `MCPTool`)
2. Каждый инструмент задекорирован `@error_boundary` (JSON + таймаут)
3. Единственное место создания зависимостей — `create_service_collection()`
4. LSP и MCP используют один DI контейнер (нет дублирования)

**Важно:** при разработке MCP-инструментов основной файл — `src/mcp/server.py` (функция `create_mcp_server()`). `src/hybrid_server.py` — точка входа, которая запускает LSP и MCP вместе.

---

## 3. Стиль кода

- **Formatter**: Black (line length 88)
- **Порядок импортов**: isort
- **Типизация**: обязательны для публичных API
- **Логирование**: `logging.getLogger(__name__)` — никогда `print()` в production-коде
- **Async**: используйте `async/await` для I/O-операций; тяжёлые дисковые операции — через `asyncio.to_thread()`

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

В проекте **391+ тестов** в директории `tests/`. Запуск через `pytest` с маркерами.

```powershell
# Полный набор
pytest tests/ -v

# Только быстрые тесты (без slow и integration)
pytest tests/ -v -m "not slow and not integration and not benchmark"

# По маркеру
pytest tests/ -v -m slow
pytest tests/ -v -m integration
pytest tests/ -v -m benchmark

# По модулю
pytest tests/test_searcher.py -v
pytest tests/test_parser.py -v
pytest tests/test_cross_repo_search.py -v

# С покрытием
pytest tests/ --cov=src --cov-report=term-missing

# Конкретный тест
pytest tests/test_searcher.py::TestSearcher::test_basic_search -v
```

**Маркеры** (определены в `pyproject.toml`):
- `slow` — медленные тесты
- `integration` — интеграционные тесты (требуют LM Studio)
- `benchmark` — бенчмарки производительности
- `asyncio` — async-тесты

Все тесты должны проходить перед созданием PR.

### Структура тестов

| Файл | Тестов | Тип | Что покрывает |
|------|--------|-----|--------------|
| `test_agentic_search.py` | 20 | unit, async | Агентный поиск: маршрутизация, уточнение запросов |
| `test_reranker.py` | 27 | unit, async | Рерайкнер: ранжирование, веса, edge cases |
| `test_symbol_index_call_graph.py` | 22 | unit | Граф вызовов: построение, обход, циклические зависимости |
| `test_cross_repo_search.py` | 21 | unit | Кросс-репозиторийный поиск: слияние результатов |
| `test_deep_search.py` | 15 | unit | Глубокий поиск: итерации, уточнение, стоп-условия |
| `test_index_progress.py` | 11 | unit | Прогресс индексации: статусы, переходы состояний |
| `test_indexer_project_path.py` | 6 | unit | Пути индексатора: нормализация, валидация |
| `test_parser.py` | 4 | unit | Парсер: AST-извлечение, синтаксические ошибки |
| `test_integration.py` | 3 | integration | Интеграция с реальной LanceDB |
| `benchmark_agentic_search.py` | 6 | benchmark | Производительность агентного поиска |

### Категории тестов

- **Unit (129 тестов)** — не требуют внешних сервисов, время < 5 сек
- **Integration (3 теста)** — требуют LanceDB, маркированы `@pytest.mark.integration`
- **Benchmark (6 тестов)** — замеры latency/throughput, не в обычном прогоне
- **Async** — `test_agentic_search.py` и `test_reranker.py` используют `pytest-asyncio`

### CI-пайплайн

```bash
# Минимальный (каждый коммит)
pytest tests/ -m "not integration and not benchmark" --tb=short -q

# Полный (ночной прогон)
pytest tests/ --tb=long -v
```

Требования к CI: Python 3.10+, `pytest`, `pytest-asyncio`, `pytest-cov`.

---

## 5. Добавление новых MCP инструментов

Все 33 MCP-инструмента определены в `src/mcp/server.py` внутри функции `create_mcp_server()`.

### Основные инструменты:

| Категория | Инструменты |
|-----------|-------------|
| **Поиск** | `search_code(query, mode)`, `structural_search`, `cross_repo_search`, `cross_project_deps` |
| **Индекс** | `get_index_status`, `get_index_progress`, `get_index_timeline`, `index_project_dir`, `notify_change`, `index_health` |
| **Символы** | `get_symbol_info`, `impact_analysis`, `get_repo_map`, `get_repo_rank` |
| **Система** | `get_health_report`, `watcher_status`, `get_logs`, `generate_chunk_summaries` |
| **Аналитика** | `get_hotspots`, `get_bug_correlation`, `get_related_files`, `graph_query` |
| **Git** | `get_commit_history`, `get_file_history`, `get_branch_info` |
| **Фон** | `submit_background_task`, `get_task_status` |

> 🔄 `smart_search`, `deep_search`, `context_search` — deprecated, используйте `search_code(query, mode=...)`

### Шаги для добавления нового инструмента:

1. **Реализуйте функцию** в `src/mcp/server.py` внутри `create_mcp_server()`:

```python
@mcp.tool()
def my_new_tool(param: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
    """Описание инструмента для AI-агента.

    ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ КОГДА:
    - Сценарий использования 1
    - Сценарий использования 2

    Args:
        param: Описание параметра

    Returns:
        Описание возвращаемого значения
    """
    _debug_log("my_new_tool", param)
    try:
        # Реализация
        return f"✅ Результат: {param}"
    except Exception as e:
        logger.error(f"Ошибка my_new_tool: {e}", exc_info=True)
        return f"❌ Ошибка: {e}"
```

2. **Добавьте `_debug_log()`** — это маркерная запись в `mcp_debug.log` для отладки живости сервера.

3. **Обработайте ошибки** — никогда не бросайте исключение наружу. Верните строку с `❌`.

4. **Добавьте тест** в `tests/test_<module>.py`:

```python
def test_my_new_tool():
    from src.mcp.server import create_mcp_server
    mcp = create_mcp_server()
    # Тест логики
```

5. **Обновите документацию**:
   - `README.md` — секция «Tools» → обновите категорию и описание
   - `docs/architecture.md` — добавьте описание инструмента
   - `CHANGELOG.md` — добавьте запись

6. **Проверьте форматирование**:

```powershell
black src/mcp/server.py
isort src/mcp/server.py
pytest tests/ -v
```

---

## 6. Добавление новых модулей ядра

Ядро находится в `src/core/`. Существующие модули:

| Модуль | Назначение |
|---|---|
| `indexer.py` | Индексация файлов в LanceDB |
| `searcher.py` | Семантический поиск + agentic search |
| `parser.py` | Парсинг кода (Tree-sitter) |
| `reranker.py` | Мульти-провайдерный реранкинг |
| `symbol_index.py` | Индекс символов + Call Graph |
| `structural_search.py` | AST-паттерны |
| `multi_project_searcher.py` | Cross-repo поиск |
| `file_guard.py` | Фильтрация файлов (.gitignore) |
| `gitignore_parser.py` | Парсинг .gitignore |
| `log_manager.py` | Файловое логирование |
| `remote_embedder.py` | Клиент LM Studio/Ollama/ONNX |

### Шаги для добавления нового модуля:

1. **Создайте файл** в `src/core/my_module.py`:

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

2. **Импортируйте и подключите** в `src/mcp/server.py`:

```python
from src.core.my_module import MyModule

# Внутри create_mcp_server():
my_module = MyModule(...)
```

3. **Добавьте тест** в `tests/test_my_module.py`:

```python
import pytest
from src.core.my_module import MyModule

class TestMyModule:
    def test_basic(self):
        module = MyModule()
        result = module.do_something()
        assert result is not None
```

4. **Обновите `docs/architecture.md`** — добавьте модуль в диаграмму компонентов.

---

## 7. Сообщения коммитов

Формат Conventional Commits: `type(scope): description`

**Типы:**
- `feat` — новая функциональность
- `fix` — исправление бага
- `docs` — документация
- `test` — добавление/исправление тестов
- `refactor` — рефакторинг без изменения поведения
- `perf` — улучшение производительности
- `chore` — обслуживание (зависимости, конфигурация)

**Scopes:** `searcher`, `indexer`, `parser`, `reranker`, `mcp`, `lsp`, `core`, `tests`, `docs`

**Примеры:**
```
feat(searcher): add BM25 hybrid search implementation
fix(indexer): handle empty embeddings from LM Studio
docs: update README with architecture diagram
test(cross-repo): add @-mention parsing tests
refactor(mcp): extract debug logging to shared utility
perf(symbol_index): cache call graph results
```

---

## 8. Процесс PR

### Чек-лист перед созданием PR:

- [ ] Ветка создана от `development` (не `main`)
- [ ] `pytest tests/ -v` — все тесты проходят
- [ ] `black --check src/` — форматирование соответствует
- [ ] `isort --check-only src/` — импорты отсортированы
- [ ] Type hints на всех публичных функциях
- [ ] Нет `print()` в production-коде (только `logging`)
- [ ] Новые инструменты/модули покрыты тестами
- [ ] `CHANGELOG.md` обновлён
- [ ] `README.md` обновлён (если изменился публичный API)
- [ ] `docs/architecture.md` обновлён (если изменилась архитектура)

### Описание PR должно содержать:

1. **Что изменено** — конкретные файлы и функции
2. **Зачем** — какую проблему решает
3. **Как протестировано** — какие тесты добавлены/прогнаны
4. **Breaking changes** — если есть, явно указать

### Процесс:

1. Создайте PR в GitHub
2. Дождитесь review
3. Исправьте замечания
4. Merge в `development` (не в `main` напрямую)

---

## 9. Версионирование

SemVer: MAJOR.MINOR.PATCH

- **MAJOR** — несовместимые изменения API
- **MINOR** — новые инструменты/возможности (обратно совместимые)
- **PATCH** — багфиксы

Текущая версия в `pyproject.toml`: `1.2.0`

---

## 10. Устранение неполадок для контрибьюторов

| Проблема | Решение |
|---|---|
| `ModuleNotFoundError: No module named 'src'` | Убедитесь что запускаете из корня проекта |
| `mcp` импортируется из `src/mcp/` вместо библиотеки | Проверьте `sys.path` — `src/` должен быть добавлен ПОСЛЕ импорта mcp |
| Тесты падают с ошибкой эмбеддинга | Нормально для fallback-режима; для полного тестирования запустите LM Studio |
| `WinError 5` при запуске | Используйте `src/hybrid_server.py` (один процесс вместо двух) |

---

*Последнее обновление: 2026-07-05*
