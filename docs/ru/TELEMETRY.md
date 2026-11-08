# Телеметрия

> Перевод: 2026-11-08, источник — docs/en/TELEMETRY.md. Английская версия — канон.

[English](../en/TELEMETRY.md) · [Русский](TELEMETRY.md) · [中文](../zh/TELEMETRY.md)

> Версия 3.5.0. Всё на этой странице локально. Сервер ничего не отправляет в сеть
> и не имеет эндпоинта аналитики.

---

## 1. Два независимых сборщика

| Сборщик | Что хранит | Где живёт | Срок жизни |
|---|---|---|---|
| Метрики по инструментам | вызовы, ошибки, выборки задержки, доля повторов, маршрут | `<ext_root>/telemetry/tool_metrics.json` | переживает перезапуски (пишется каждые 10 вызовов и при выходе) |
| Ежедневные снимки | счётчики runtime, размер индекса, RAM/CPU, пинг провайдера | `<data_root>/projects/<hash8>/telemetry/YYYY-MM-DD.json` | 90 дней, затем вычищаются |

`<ext_root>` — это каталог, из которого запускается код
(`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`).
`<data_root>` — это `%LOCALAPPDATA%\mscodebase` на Windows,
`~/Library/Caches/mscodebase` на macOS, `~/.cache/mscodebase` на Linux;
переопределяется через `MSCODEBASE_DATA_DIR`. `<hash8>` — это
`md5(normalised project path)[:8]` (`artifact_paths.project_hash`).

Ни один из сборщиков не является логом пользовательских промптов. Хранилища
полезной нагрузки запросов/ответов нет: аргументы инструментов и текст кода в
телеметрию не пишутся.

## 2. Метрики по инструментам

`@error_boundary` вызывает `record_tool_call()` до и `record_tool_result()` после
каждого вызова инструмента. По каждому инструменту хранится:

- `calls`, `errors`, `total_ms`, `min_ms`;
- ограниченная выборка задержек (`deque(maxlen=1000)`) — P50/P95/P99 считаются по
  **последним 1000 вызовам**, а не по всей истории;
- `repeat_count` (тот же инструмент вызван дважды подряд) как доля вызовов;
- время простоя между вызовами и счётчик `route`, когда инструмент его сообщает.

Сохранение: обработчик `atexit` плюс сброс каждые 10 вызовов записывают весь
реестр в `<ext_root>/telemetry/tool_metrics.json` через временный файл и
`os.replace` (атомарно, без полузаписанного JSON). Метрики **не** загружаются
обратно при старте, поэтому файл — это снимок завершённых сессий, а не
накопительная база.

Читать это можно так:

| Инструмент | Профиль | Возвращает |
|---|---|---|
| `intel_tool_health()` | full | полоса здоровья, вызовы, P50/P95, доля повторов, маршруты, доля простоя против активности |
| `intel_execution_timeline(limit=15)` | full | последние N вызовов с инструментом, ms, ok/fail, маршрут, уверенность |
| `intel_get_telemetry(days=7)` | full | счётчики runtime + сводка по инструментам + ресурсы + пинг провайдера + история |

`intel_get_telemetry` — единственный, кто ещё и пишет снимок (см. §3).
Инструмента `get_index_status` нет — состояние индекса это
`codebase(action="index", path="status")`.

## 3. Ежедневные снимки

Каждый вызов `intel_get_telemetry()` добавляет одну запись в
`<data_root>/projects/<hash8>/telemetry/<date>.json`. Файл — это JSON-массив;
форма ниже, значения иллюстративные:

```json
[{
  "date": "2026-11-08",
  "captured_at": "2026-11-08T12:34:56",
  "uptime_sec": 1234.5,
  "counters": { "can_execute_calls": 12, "verdict_ready": 12, "total_wait_time_sec": 0.0 },
  "project": { "project_path": "...", "index_chunks": 0, "index_files": 0 },
  "resources": { "rss_mb": 0, "cpu_percent": 0 },
  "llm": { "ping_ms": 0.0, "batch_10_ms": 0.0, "tokens_per_sec": 0,
           "provider": "fallback", "model": "...", "configured_model": "..." },
  "token_savings": { "avg_savings_percent": 95.0, "total_searches": 0 },
  "_meta": { "index_age_days": 0 }
}]
```

Замечания о полях, которые легко переоценить:

- `llm` измеряется реальным эмбеддингом `"ping"` и пакета из десяти; если
  провайдер недоступен, вместо этого ключом становится `{"error": ...}`.
  `provider` — это живой режим (`onnx`, `llama_cpp`, `lm_studio`, `ollama`,
  `onnx_server`, `fallback`), а не сконфигурированное предпочтение.
- Если какая-то секция падает, эта секция становится `{"error": "..."}` — снимок
  всё равно записывается. Частичный снимок — это сигнал, а не сломанный файл.
- `token_savings.avg_savings_percent` — фиксированная константа в писателе, а не
  измерение. Не цитируйте её.

## 4. Счётчики runtime

`get_runtime_counters()` (полный профиль) форматирует
`runtime_coordinator._COUNTERS`: `can_execute_calls`, `verdict_ready`,
`verdict_blocked_system_path`, `verdict_blocked_not_ready`,
`verdict_blocked_failed`, `verdict_blocked_resolution`,
`verdict_blocked_registry_error`, `warnings_bridge_not_synced`,
`warnings_indexing_in_progress`, `warnings_just_started`, `total_wait_time_sec`.

При нуле проверок он печатает «Checks: 0 — данных нет», а не «100% blocked»,
потому что отношение с пустым знаменателем — не измерение.

## 5. Автономный сборщик

Для снимка без запущенной MCP-сессии:

```bash
python scripts/collect_telemetry.py            # one snapshot into data_root/.../telemetry
python scripts/collect_telemetry.py --history 7 # print the last 7 days as JSON
python scripts/collect_telemetry.py --daily     # register a Windows scheduled task (23:00)
```

Запланированная задача использует `pythonw.exe`, когда он есть, поэтому не
мигает консольным окном. Скрипт разрешает проект через `resolve_project_root()` и
пишет через `artifact_paths.get_telemetry_dir()`, так что он никогда не мусорит в
каталоге проекта.

## 6. Ресурсы

RAM/CPU приходят из `src/core/indexing/resource_monitor.py`
(`get_global_resource_monitor().get_summary()`), сэмплируются монитором, а не
считаются по требованию. `get_health_report()` показывает те же числа плюс
предупреждения о диске: ниже `MIN_FREE_DISK_MB = 500` data root получает
предупреждение.

## 7. Хранение и очистка

`artifact_gc.prune_stale_artifacts()` работает в фоновом потоке через 3 s после
старта:

- файлы телеметрии старше **90 дней** удаляются;
- неактивные папки проектов (без записей **30 дней**) удаляются целиком, если
  проект не активен в реестре;
- логи старше **7 дней** вычищаются;
- заблокированные файлы пропускаются и перечисляются в отчёте, но никогда не
  удаляются принудительно.

Значения по умолчанию живут в `artifact_gc.py` (`DEFAULT_TELEMETRY_MAX_AGE_DAYS`,
`DEFAULT_PROJECT_MAX_AGE_DAYS`, `DEFAULT_LOG_RETENTION_DAYS`).

## 8. Сводка по приватности

- Всё остаётся на машине; пути выгрузки в коде нет.
- Ни текст исходников, ни промпт, ни аргумент инструмента не сохраняются.
- Содержимое `read_live_file`, абсолютные пути из ошибок и traceback'и
  логируются (но не возвращаются в ответах); `src/core/redact.py` вырезает формы
  учётных данных с префиксом до того, как текст дойдёт до контекста агента, и
  явно не является границей.
- Удаление `<data_root>/projects/<hash8>/telemetry/` безопасно: оно убирает
  историю и оставляет индекс, граф и память нетронутыми.

---

**Verified against:** `src/core/error_handler.py` (`record_tool_call`,
`get_tool_metrics_summary`, `set_metrics_path`, deque size, save cadence),
`src/mcp/server_factory.py` (`set_metrics_path(_ext_root/telemetry/...)`),
`src/core/intelligence/layer.py` (`intel_get_telemetry` snapshot writer),
`src/core/intelligence/tools_reg.py` (`intel_get_telemetry` registration),
`src/utils/ui_formatter.py` (`format_telemetry`),
`src/mcp/server_tools.py` (`get_runtime_counters`, `intel_tool_health`,
`intel_execution_timeline`), `src/core/runtime_coordinator.py` (counter names),
`src/core/artifact_paths.py` (data-root layout), `src/core/artifact_gc.py`
(retention), `scripts/collect_telemetry.py`, `src/core/redact.py`.
