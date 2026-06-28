# Тестирование MSCodeBase

Актуальное состояние тестов: **133 теста** в 11 модулях + 6 бенчмарков. Все тесты содержат реальные ассерты, без моков-заглушек.

---

## Структура тестов

| Файл | Тестов | Тип | Что покрывает |
|---|---|---|---|
| `test_agentic_search.py` | 20 (3 класса) | unit, async | Агентный поиск: маршрутизация, уточнение запросов, обработка пустых результатов |
| `test_reranker.py` | 27 (функции, async) | unit, async | Рерайкнер: ранжирование, веса, edge cases, пустые входы |
| `test_symbol_index_call_graph.py` | 22 | unit | Граф вызовов: построение, обход, циклические зависимости |
| `test_cross_repo_search.py` | 21 (3 класса) | unit | Кросс-репозиторийный поиск: слияние результатов, фильтрация по проектам |
| `test_deep_search.py` | 15 (4 класса) | unit | Глубокий поиск: итерации, уточнение, стоп-условия |
| `test_index_progress.py` | 11 (4 класса) | unit | Прогресс индексации: статусы, переходы состояний, ошибки |
| `test_indexer_project_path.py` | 6 | unit | Пути индексатора: нормализация, валидация, резолвинг |
| `test_parser.py` | 4 | unit | Парсер: AST-извлечение, обработка синтаксических ошибок |
| `test_integration.py` | 3 | integration | Интеграция с реальной LanceDB: запись, чтение, удаление |
| `test_connection.py` | 1 | smoke | Проверка импорта модулей (без ассертов) |
| `benchmark_agentic_search.py` | 6 (5 классов) | benchmark | Производительность агентного поиска: latency, throughput |

---

## Запуск тестов

### Все тесты
```bash
pytest tests/ -v
```

### Только unit-тесты (быстро, без внешних зависимостей)
```bash
pytest tests/ -v -m "not integration and not benchmark"
```

### Конкретный модуль
```bash
pytest tests/test_reranker.py -v
```

### Интеграционные тесты (требует LanceDB)
```bash
pytest tests/test_integration.py -v -m integration
```

### Бенчмарки
```bash
pytest tests/benchmark_agentic_search.py -v -m benchmark
```

### С покрытием
```bash
pytest tests/ --cov=mcp --cov-report=term-missing -m "not integration and not benchmark"
```

---

## Маркеры pytest

| Маркер | Назначение | Когда использовать |
|---|---|---|
| `slow` | Тесты > 1 сек | Долгие интеграционные проверки |
| `integration` | Требуют LanceDB | Запуск только в CI или локально с поднятой БД |
| `benchmark` | Замеры производительности | Ручной запуск, не в CI |

Конфигурация маркеров — в `pyproject.toml` под `[tool.pytest.ini_options]`.

---

## Категории тестов

### Unit (129 тестов)
- Не требуют внешних сервисов
- Работают изолированно
- Время выполнения: < 5 сек суммарно

### Integration (3 теста)
- Требуют запущенную LanceDB
- Проверяют реальную запись/чтение векторов
- Маркированы `@pytest.mark.integration`

### Benchmark (6 тестов)
- Замеряют latency и throughput
- Не входят в обычный прогон
- Маркированы `@pytest.mark.benchmark`

### Async
- `test_agentic_search.py` и `test_reranker.py` используют `pytest-asyncio`
- Запускаются автоматически, дополнительных флагов не требуют

---

## CI-пайплайн

### Минимальный (каждый коммит)
```bash
pytest tests/ -m "not integration and not benchmark" --tb=short -q
```

### Полный (ночной прогон)
```bash
pytest tests/ --tb=long -v
```

### Требования к CI
- Python 3.10+
- `pytest`, `pytest-asyncio`, `pytest-cov`
- Для integration: LanceDB-совместимое хранилище (локальное)

---

## Покрытие и пробелы

### Что покрыто ✅
- Агентный поиск (маршрутизация, итерации)
- Рерайкнер (все сценарии ранжирования)
- Граф вызовов (построение, обход)
- Кросс-репо поиск (слияние, фильтрация)
- Глубокий поиск (итерации, стоп-условия)
- Прогресс индексации (состояния, ошибки)
- Пути индексатора (нормализация)
- Парсинг AST

### Что НЕ покрыто ❌
| Модуль | Что отсутствует | Приоритет |
|---|---|---|
| `mcp/tools.py` | Нет тестов на MCP-инструменты | Высокий |
| `main.py` | Нет тестов на точку входа | Средний |
| `file_guard.py` | Нет прямых тестов на защиту файлов | Средний |
| `mcp/server.py` | Нет тестов на запуск сервера | Низкий |

---

## Добавление нового теста

1. Именование: `test_<модуль>.py`
2. Асинхронные тесты: `@pytest.mark.asyncio`
3. Интеграционные: `@pytest.mark.integration`
4. Бенчмарки: `@pytest.mark.benchmark`
5. Каждый тест — минимум один реальный ассерт (без `pass` без проверки)

Пример структуры:
```python
import pytest

class TestNewFeature:
    def test_basic_case(self):
        result = feature(input)
        assert result == expected

    @pytest.mark.asyncio
    async def test_async_case(self):
        result = await async_feature(input)
        assert result.is_valid()
```
