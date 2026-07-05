# Measurement Plan — MSCodeBase Intelligence

Архитектура без метрик — это забор. Ниже — план сбора данных для доказательства
(или опровержения) эффективности каждого архитектурного изменения.

## 1. Что измеряем

### RuntimeCoordinator counters (уже добавлены)

| Счётчик | Что показывает | Цель |
|---|---|---|
| `can_execute_calls` | Всего вызовов | Базовое число |
| `verdict_ready` | Разрешённых запросов | > 95% |
| `verdict_blocked_system_path` | Блокировок системного пути | 0 (хорошо) |
| `verdict_blocked_not_ready` | Блокировок неготовности | < 5% — если больше, проект медленно стартует |
| `verdict_blocked_failed` | Ошибок инициализации | < 1% |
| `verdict_blocked_resolution` | Ошибок резолва проекта | < 1% |
| `warnings_bridge_not_synced` | LSP не синхронизирован | Должно снижаться |
| `total_wait_time_sec` | Суммарное время ожидания | Характеризует задержки |

**Запуск:** `get_runtime_counters()` в MCP.

### ProjectContext capture time (нужно добавить в v2.5)

> Сколько миллисекунд занимает `ProjectContext.capture()`.
> Если > 500ms — snapshot слишком тяжёлый, нужно кэширование.

### Bridge latency (нужно добавить в v2.5)

> Время между `write_active_project` (LSP) и `read_project_from_bridge` (MCP).
> Если > 2s — race condition при переключении окон.

## 2. Процесс сбора

1. Раз в день вызывать `get_runtime_counters()`.
2. Записывать в файл `.mscodebase/telemetry/counters.json`.
3. Сравнивать день к дню.

## 3. Целевые показатели (через месяц)

| Метрика | Текущее | Цель |
|---|---|---|
| `verdict_ready / can_execute_calls` | ? | > 95% |
| bridge sync latency (p95) | ? | < 2s |
| `ProjectContext.capture()` | ? | < 200ms |
| Аномалий (blocked > 5%) | ? | 0 в неделю |

## 4. Что НЕ будем измерять (пока)

- Project Memory accuracy (нет baseline)
- Incident Memory recall (нет baseline)
- Knowledge Snapshot quality (гипотеза)
