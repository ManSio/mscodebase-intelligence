# Telemetry — сбор метрик работы MCP

[🇬🇧 English](../en/TELEMETRY.md) • [🇷🇺 Русский](TELEMETRY.md) • [🇨🇳 中文](../zh/TELEMETRY.md)

Автоматический сбор метрик для построения графиков и анализа производительности.

## Как это работает

Работают две независимые системы сбора метрик:

### 1. Per-Tool метрики (в процессе, автосохранение)

Каждый вызов любого MCP-инструмента автоматически записывается декоратором
`error_boundary`. Метрики хранятся в памяти и сохраняются в JSON каждые 10 вызовов
+ при остановке сервера:

```
{ext_root}/telemetry/tool_metrics.json
```

**Пример таблицы** (отображается через `intel_get_telemetry`):

| Инструмент | Вызовов | Ошибок | Мин мс | Сред мс | Макс мс | Последний |
|------------|---------|--------|--------|---------|---------|----------|
| search_code | 31 | 0 | 1676 | 2525 | 14264 | 23:04:41 |
| structural_search | 20 | 0 | 35 | 2179 | 4479 | 23:07:44 |
| impact_analysis | 4 | 0 | 1343 | 1353 | 1370 | 23:03:49 |
| get_symbol_info | 3 | 0 | 1332 | 1338 | 1348 | 23:00:55 |

Метрики сохраняются между перезапусками MCP-сервера — `load_metrics()`
читает сохранённый JSON при старте.

### 2. Внешний сборщик (по расписанию)

Скрипт `scripts/collect_telemetry.py` собирает снимок всех runtime-счётчиков
и сохраняет в JSON-файл с датой. Файлы накапливаются в директории:

```
.mscodebase/telemetry/
├── 2026-07-05.json    ← все снимки за 5 июля
├── 2026-07-06.json    ← все снимки за 6 июля
└── ...

---

### 🔗 Связанные документы

| Документ | Описание |
|----------|----------|
| [README.md](README.md) | Главная документация, карта всех доков |
| [TELEMETRY.md](TELEMETRY.md) | Этот файл |
| [CHANGELOG.md](CHANGELOG.md) | История версий |
```

Каждый файл — массив записей:
```json
[
  {
    "date": "2026-07-05",
    "captured_at": "2026-07-05T23:00:00",
    "uptime_sec": 43200,
    "counters": {
      "can_execute_calls": 152,
      "verdict_ready": 148,
      "verdict_blocked_not_ready": 3,
      "verdict_blocked_system_path": 0,
      "total_wait_time_sec": 2.4,
      "warnings_bridge_not_synced": 1,
      "warnings_indexing_in_progress": 2
    },
    "project": {
      "project_path": "D:\\Project\\MSCodeBase",
      "state": "READY",
      "index_chunks": 1362,
      "index_files": 106,
      "index_symbols": 1080,
      "index_latency_ms": 13.2
    }
  }
]
```

## Использование

### Разовый сбор
```bash
python scripts/collect_telemetry.py
```

### Настроить ежедневный сбор в 23:00
```bash
python scripts/collect_telemetry.py --daily
```
Создаёт задачу в планировщике Windows "MSCodeBase Telemetry Collector".

### Просмотр истории за N дней
```bash
python scripts/collect_telemetry.py --history 7
```
Выводит JSON за последние 7 дней.

## Какие метрики собираются

### Runtime счётчики (из RuntimeCoordinator)

| Метрика | Что показывает |
|---|---|
| `can_execute_calls` | Сколько раз MCP проверял готовность проекта |
| `verdict_ready` | Сколько раз проект был готов (норма) |
| `verdict_blocked_not_ready` | Сколько раз проект был не готов (требуется реиндексация) |
| `verdict_blocked_system_path` | Сколько раз пытались работать с системной директорией |
| `verdict_blocked_failed` | Сколько раз проект не смог инициализироваться |
| `verdict_blocked_resolution` | Сколько раз не удалось определить проект |
| `verdict_blocked_registry_error` | Сколько раз Registry ошибался |
| `warnings_bridge_not_synced` | Сколько раз LSP не был синхронизирован |
| `warnings_indexing_in_progress` | Сколько раз индексация была в процессе |
| `warnings_just_started` | Сколько раз MCP только запустился |
| `total_wait_time_sec` | Сколько секунд MCP ждал готовности проекта |

### Project statistics

| Метрика | Что показывает |
|---|---|
| `state` | Текущее состояние проекта (READY/INDEXING/FAILED) |
| `index_chunks` | Количество чанков в LanceDB |
| `index_files` | Количество проиндексированных файлов |
| `index_symbols` | Количество распознанных Tree-sitter символов |
| `index_latency_ms` | Время получения статуса индекса |

### Passport

| Метрика | Что показывает |
|---|---|
| `uptime_sec` | Сколько секунд работает MCP-процесс |
| `run_id` | Уникальный ID запуска |
| `build_id` | Git commit hash |

## Построение графиков

Накопившиеся JSON-файлы можно загрузить в любую BI-систему:

- **Excel** — импорт JSON через Power Query
- **Grafana** — если добавить HTTP-сервер, отдающий эти файлы
- **Python/matplotlib** — `python scripts/collect_telemetry.py --history 30`

## Что считать нормой

| Метрика | Хорошо | Тревожно |
|---|---|---|
| `verdict_ready / can_execute_calls` | > 95% | < 80% |
| `verdict_blocked_not_ready` | < 5% | > 20% |
| `verdict_blocked_system_path` | 0 | > 1 |
| `total_wait_time_sec` | < 10s/день | > 60s/день |
| `warnings_bridge_not_synced` | < 3/день | > 20/день |
| `index_latency_ms` | < 50ms | > 500ms |
