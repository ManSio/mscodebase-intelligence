# Telemetry — Сбор метрик выполнения MCP

[🇬🇧 English](../en/TELEMETRY.md) • [🇷🇺 Русский](TELEMETRY.md) • [🇨🇳 中文](../zh/TELEMETRY.md)

Автоматический сбор метрик для построения графиков и анализа производительности.

## Как это работает

Две независимые телеметрические системы собирают метрики:

### 1. Метрики по инструментам (в процессе, автосохранение)

Каждый вызов любого MCP-инструмента автоматически записывается декоратором `error_boundary`.
Метрики хранятся в памяти и сохраняются в JSON каждые 10 вызовов + при завершении:

```
{ext_root}/telemetry/tool_metrics.json
```

**Пример таблицы** (видна через `intel_get_telemetry`):

| Инструмент | Вызовы | Ошибки | Мин мс | Сред мс | Макс мс | Последний вызов |
|------|-------|--------|--------|--------|--------|-----------|
| search_code | 31 | 0 | 1676 | 2525 | 14264 | 23:04:41 |
| structural_search | 20 | 0 | 35 | 2179 | 4479 | 23:07:44 |
| impact_analysis | 4 | 0 | 1343 | 1353 | 1370 | 23:03:49 |
| get_symbol_info | 3 | 0 | 1332 | 1338 | 1348 | 23:00:55 |

Метрики сохраняются между перезапусками MCP-сервера — `load_metrics()` читает сохранённый JSON при запуске.

### 2. Внешний сборщик (плановые снэпшоты)

Скрипт `scripts/collect_telemetry.py` делает снэпшот всех счётчиков выполнения
и сохраняет его в JSON-файл с датой. Файлы накапливаются в директории:

```
.mscodebase/telemetry/
├── 2026-07-05.json    ← все снэпшоты за 5 июля
├── 2026-07-06.json    ← все снэпшоты за 6 июля
└── ...
```

Каждый файл представляет собой массив записей:
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

### 🔗 Связанные документы

| Документ | Описание |
|----------|-------------|
| [README.md](../../README.md) | Основная документация, карта всех доков |
| [TELEMETRY.md](TELEMETRY.md) | Этот файл |
| [CHANGELOG.md](CHANGELOG.md) | История версий |
| [KNOWN_ISSUES.md](../../KNOWN_ISSUES.md) | Известные проблемы, включая профиль RAM (KI-002) |

## Использование

### Единоразовый сбор
```bash
python scripts/collect_telemetry.py
```

### Плановый ежедневный сбор в 23:00
```bash
python scripts/collect_telemetry.py --daily
```
Создаёт задачу в Планировщике Windows «MSCodeBase Telemetry Collector».

### Просмотр истории за N дней
```bash
python scripts/collect_telemetry.py --history 7
```
Выводит JSON за последние 7 дней.

## Собираемые метрики

### Счётчики выполнения (из RuntimeCoordinator)

| Метрика | Что показывает |
|--------|---------------|
| `can_execute_calls` | Сколько раз MCP проверял готовность проекта |
| `verdict_ready` | Сколько раз проект был готов (норма) |
| `verdict_blocked_not_ready` | Сколько раз проект не был готов (нужна переиндексация) |
| `verdict_blocked_system_path` | Сколько раз была попытка работы с системной директорией |
| `verdict_blocked_failed` | Сколько раз проект не смог инициализироваться |
| `verdict_blocked_resolution` | Сколько раз определение проекта завершилось ошибкой |
| `verdict_blocked_registry_error` | Сколько раз Registry выдал ошибку |
| `warnings_bridge_not_synced` | Сколько раз LSP не был синхронизирован |
| `warnings_indexing_in_progress` | Сколько раз индексация была в процессе |
| `warnings_just_started` | Сколько раз MCP только что запустился |
| `total_wait_time_sec` | Сколько секунд MCP ждал готовности проекта |

### Статистика проекта

| Метрика | Что показывает |
|--------|---------------|
| `state` | Текущее состояние проекта (READY/INDEXING/FAILED) |
| `index_chunks` | Количество чанков в LanceDB |
| `index_files` | Количество проиндексированных файлов |
| `index_symbols` | Количество распознанных символов Tree-sitter |
| `index_latency_ms` | Время получения статуса индекса |

### Паспорт

| Метрика | Что показывает |
|--------|---------------|
| `uptime_sec` | Сколько секунд работает MCP-процесс |
| `run_id` | Уникальный ID запуска |
| `build_id` | Хэш коммита Git |

## Живые инструменты телеметрии (MCP)

Помимо фонового сборщика (`scripts/collect_telemetry.py`), метрики доступны вживую через MCP-инструменты:

### `intel_get_telemetry`
Снимок рантайма процесса:
- **Runtime State**: Ready/Blocked, Warnings, Total wait
- **Per-Tool Calls**: таблица `Tool | Calls | Errors | Min/Avg/Max ms | Last call`
- **Resources**: `RAM` (MB), `CPU` (%), `Threads`
- **LLM Provider**: модель, ping, batch-10 latency, throughput (tok/s)
- **ETA Predictor**: `Total measurements`, `Learned: N/8 ops`
- **History**: последние снэпшоты (дата / chunks / files / RAM / LLM ping)

### `intel_execution_timeline`
Таблица последних вызовов: `Time | Tool | ms | Status | Route | Confidence | Results`. Реальная латентность каждого инструмента в живой сессии.

### `get_runtime_counters`
`Checks` / `Ready` / `Blocked` (%), `Blocks`, `Warnings`, `Performance.Wait`.

### `debug_runtime_passport`
Расширенный passport: `RUN_ID`, `BUILD_ID`, `PID`, `Uptime`, `CWD`, `Ext Root`, `Bridge State`, `Registry`, `Env`.

### `intel_tool_health`
Дашборд здоровья инструментов: success rate, latency, confidence, routes.

### Пример (живой прогон 2026-07-12)

| Tool | Calls | Avg ms | Статус |
|------|-------|--------|--------|
| get_index_status | 1 | 295 | ✅ |
| get_symbol_info | 1 | 1611 | ✅ |
| impact_analysis | 1 | 1588 | ✅ |
| search_code | 1 | 1651 | ✅ |
| rename_symbol | 1 | 2624 | ✅ (preview) |
| get_health_report | 1 | 21618 | ✅ (тяжёлый: скан логов) |

> RAM MCP-сервера в idle ~1GB, пик ~2.8GB под нагрузкой (НЕ утечка, см. KNOWN_ISSUES KI-002).

---

## Модельный конвейер (актуально, 2026-07-12)

Конвейер эмбеддинга/реренкинга — **локальный и in-process**. Внешний LLM-сервер для
семантического поиска **не требуется**:

| Этап | Движок | Модель | Примечание |
|------|--------|--------|-----------|
| Embedding | ONNX INT8 / OpenVINO INT8 (in-process) | `intfloat/multilingual-e5-base` (768-dim) | ~350 ch/s на Windows CPU. Файл: `model_quantized.onnx`. LM Studio — **только fallback-провайдер**. |
| Reranker | llama.cpp (`llama-server.exe`, отдельный процесс, `:8081`) | `BAAI/bge-reranker-v2-m3` (GGUF Q4_K_M) | Грузится шагом `step_gguf` в `install.py`. |
| LLM (RAG, опц.) | зарезервирован | — | Не нужен для поиска. |

> ⚠️ **Исправлен дрейф документации (2026-07-12):** старые телеметрийные доки описывали
> «LM Studio bge-m3 / phi-4-mini» как провайдер эмбеддинга. Это **устарело** — эмбеддинг
> переехал in-process на ONNX/OpenVINO E5-base INT8 (см. CHANGELOG 3.2.1). LM Studio остаётся
> лишь опциональным fallback, если локальная ONNX/OpenVINO модель недоступна.

---

## Построение графиков

Накопленные JSON-файлы можно загрузить в любую BI-систему:

- **Excel** — импорт JSON через Power Query
- **Grafana** — если добавить HTTP-сервер, раздающий эти файлы
- **Python/matplotlib** — `python scripts/collect_telemetry.py --history 30`

## Что считается нормой

| Метрика | Хорошо | Тревожно |
|--------|------|------------|
| `verdict_ready / can_execute_calls` | > 95% | < 80% |
| `verdict_blocked_not_ready` | < 5% | > 20% |
| `verdict_blocked_system_path` | 0 | > 1 |
| `total_wait_time_sec` | < 10 с/день | > 60 с/день |
| `warnings_bridge_not_synced` | < 3/день | > 20/день |
| `index_latency_ms` | < 50ms | > 500ms |
| MCP RAM (idle) | ~1.0 GB | > 2.0 GB устойчиво в idle |
| MCP RAM (пик под нагрузкой) | < 3.0 GB транзиент | устойчиво > 3.0 GB |

## 📊 Результаты стресс-теста (2026-07-07)

17 вызовов `search_code` — **0 ошибок, 0 таймаутов, P@5=1.00**

### Производительность режимов поиска

| Режим | Запрос | Время | Top-1 | Шум |
|------|-------|------|-------|-------|
| `fast` | `class MultiProviderReranker` | **315ms** | `reranker.py` код | 0/5 ✅ |
| `fast` | `TaskQueue` | 374ms | `task_queue.py` код | 0/6 ✅ |
| `fast` | `def can_execute` | 363ms | `runtime_coordinator.py` код | 0/6 ✅ |
| `quality` | `memory leak gc objects` | **426ms** | AGENT_DIARY.md + `intelligence_layer.py` код | 0/5 ✅ |
| `quality` | `dependency injection` | 486ms | CHANGELOG.md docs | 0/5 ✅ |
| `quality` | `RuntimeCoordinator bridge` | 1567ms | AGENTS.md архитектура | 0/5 ✅ |
| `deep` | `почему MCP не отвечает` | **~3s** | `docs/ru/FAQ.md` русская docs | 0/5 ✅ |
| `deep` | `мульти-оконность` | ~5.3s | `docs/ru/ARCHITECTURE.md` | 0/5 ✅ |

### Задержка конвейера (5 чанков `quality`)

| Этап | Движок | Время |
|-------|-------|------|
| Векторный поиск | LanceDB | ~300ms |
| Реренкинг | bge-reranker-v2-m3 (cosine sim) | ~200ms |
| **Итого** | | **~500ms** |

### Вердикт

| Аспект | Статус |
|--------|--------|
| Стабильность | ✅ 20/20 успешно |
| Точность | ✅ P@5=1.00 |
| Скорость | ✅ 500ms–5s в зависимости от режима |
| Утечки памяти | ⚠️ Нет — idle ~1GB, транзиентный пик ~2.8GB (KI-002) |

---

## 📊 Живой аудит инструментов (2026-07-12)

Полный load test: **все 59 зарегистрированных инструментов** вызваны вживую через реальный MCP-сервер.

### Поверхность инструментов
- **33 инструментов всего** = 42 core + 14 intel + 3 diagnostic (по логу старта сервера).
- **Фильтр по умолчанию**: видимы только **12 инструментов**, если не задан `MSCODEBASE_MCP_TOOLS`.
  `MSCODEBASE_MCP_TOOLS=""` — показать все 59. Запятая-список — показать подмножество.
- ~19 инструментов возвращают живые данные; ~36 скрыты фильтром по умолчанию (по дизайну, НЕ баг).

### Латентность по инструментам (живой прогон)

| Tool | Calls | Avg ms | Статус |
|------|-------|--------|--------|
| get_index_status | 1 | 295 | ✅ |
| get_symbol_info | 1 | 1611 | ✅ |
| impact_analysis | 1 | 1588 | ✅ |
| search_code | 1 | 1651 | ✅ |
| replace_symbol | 1 | 1598 | ✅ (preview) |
| rename_symbol | 1 | 2624 | ✅ (preview) |
| get_health_report | 1 | 21618 | ✅ (тяжёлый: скан логов) |

### Баги, найденные и исправленные в ходе аудита (см. KNOWN_ISSUES / CHANGELOG 3.2.1)
- **INC-58EA** — IVF-индекс «0 vectors»: `_init_onnx` грузил `model.onnx`, но на диске файл
  `model_quantized.onnx` → embedder возвращал нули → все векторы имели norm 0.0 → KMeans
  падал. Исправлено: `_init_onnx` теперь сначала берёт `model_quantized.onnx` (как `_init_openvino`).
- **INC-9573** — `intel_get_runtime_status` показывал `symbol_index_count: 0`, а
  `get_health_report` — `3197`. Исправлено: живой `get_symbol_count()` + disk reload.
- **INC-0AA6** — job зависал на 80% «Finalizing»: `await future_symbols` (Tree-sitter symbol
  indexing) не имел таймаута. Исправлено: `asyncio.wait_for(..., timeout=120)` с graceful-завершением job'а.

### Профиль RAM (замерено через `psutil`)
- Idle MCP ~1.0 GB, пик реиндексации ~1.1 GB, транзиент 2.8 GB под нагрузкой.
- Подтверждено **НЕ утечка**: транзиент 2.8 GB был от осиротевшего benchmark-процесса
  (`PID 15620`), который был убит; steady-state RSS вернулся к ~1.0 GB.
