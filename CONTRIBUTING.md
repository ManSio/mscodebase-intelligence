# Contributing — MSCodeBase Intelligence

Гайд для контрибьюторов. Версия проекта: 2.0.0+ (hybrid LSP + MCP).

---

## 1. Setup

```powershell
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd MSCodeBase
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

Требования: Python 3.11+, LM Studio (опционально, для эмбеддингов).

---

## 2. Архитектура (кратко)

| Компонент | Файл | Назначение |
|---|---|---|
| **Hybrid Server** | `src/hybrid_server.py` | Точка входа v2.0.0+: LSP + MCP в одном процессе |
| **Legacy MCP** | `src/mcp/server.py` | Чистый MCP-сервер (14 инструментов) |
| **Legacy LSP** | `src/lsp_main.py` | Отдельный LSP-сервер (для старых клиентов) |
| **Legacy Main** | `src/main.py` | Отдельный MCP-сервер (для старых клиентов) |
| **Core** | `src/core/` | Ядро: indexer, searcher, parser, reranker, symbol_index и др. |

**Важно:** при разработке MCP-инструментов основной файл — `src/mcp/server.py` (функция `create_mcp_server()`). `src/hybrid_server.py` — точка входа, которая запускает LSP и MCP вместе.

---

## 3. Code Style

- **Formatter**: Black (line length 88)
- **Import order**: isort
- **Type hints**: обязательны для публичных API
- **Logging**: `logging.getLogger(__name__)` — никогда `print()` в production-коде
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

## 4. Running Tests

В проекте **133 теста** в директории `tests/`. Запуск через `pytest` с маркерами.

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

---

## 5. Adding New MCP Tools

Все 14 MCP-инструментов определены в `src/mcp/server.py` внутри функции `create_mcp_server()`.

### Текущие инструменты:

| # | Инструмент | Назначение |
|---|---|---|
| 1 | `notify_change` | Принудительное обновление индекса файла |
| 2 | `get_index_status` | Статистика LanceDB и индекса символов |
| 3 | `get_index_progress` | Прогресс текущей индексации |
| 4 | `index_project_dir` | Запуск первичной индексации проекта |
| 5 | `search_code` | Семантический поиск (с agentic-режимом) |
| 6 | `get_symbol_info` | Call Graph для символа |
| 7 | `get_repo_map` | Карта репозитория |
| 8 | `scan_changes` | Архитектурный дифф изменений |
| 9 | `watcher_status` | Статус компонентов системы |
| 10 | `context_search` | Поиск похожего кода по фрагменту |
| 11 | `structural_search` | Поиск по AST-паттернам (Tree-sitter) |
| 12 | `deep_search` | Итеративный глубокий поиск |
| 13 | `cross_repo_search` | Поиск по нескольким проектам |
| 14 | `get_logs` | Последние ошибки из логов |

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
   - `README.md` — секция "Tools (14 total)" → обновите число
   - `ARCHITECTURE.md` — добавьте описание инструмента
   - `CHANGELOG.md` — добавьте запись

6. **Проверьте форматирование**:

```powershell
black src/mcp/server.py
isort src/mcp/server.py
pytest tests/ -v
```

---

## 6. Adding New Core Modules

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

4. **Обновите `ARCHITECTURE.md`** — добавьте модуль в диаграмму компонентов.

---

## 7. Commit Messages

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

## 8. PR Process

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
- [ ] `ARCHITECTURE.md` обновлён (если изменилась архитектура)

### Описание PR должно содержать:

1. **Что изменено** — конкретные файлы и функции
2. **Зачем** — какую проблему решает
3. **Как протестировано** — какие тесты добавлены/прогнаны
4. **Breaking changes** — если есть, явно указать

### Процесс:

1. Создайте PR в GitHub
2. Дождитесь review
3. Иправьте замечания
4. Merge в `development` (не в `main` напрямую)

---

## 9. Versioning

SemVer: MAJOR.MINOR.PATCH

- **MAJOR** — несовместимые изменения API
- **MINOR** — новые инструменты/возможности (обратно совместимые)
- **PATCH** — багфиксы

Текущая версия в `pyproject.toml`: `1.2.0`

---

## 10. Troubleshooting для контрибьюторов

| Проблема | Решение |
|---|---|
| `ModuleNotFoundError: No module named 'src'` | Убедитесь что запускаете из корня проекта |
| `mcp` импортируется из `src/mcp/` вместо библиотеки | Проверьте `sys.path` — `src/` должен быть добавлен ПОСЛЕ импорта mcp |
| Тесты падают с ошибкой эмбеддинга | Нормально для fallback-режима; для полного тестирования запустите LM Studio |
| `WinError 5` при запуске | Используйте `src/hybrid_server.py` (один процесс вместо двух) |

---

*Last updated: 2026-06-28*
