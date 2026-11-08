# Плавная деградация

> Перевод: 2026-11-08, источник — docs/en/GRACEFUL_DEGRADATION.md. Английская версия — канон.

[English](../en/GRACEFUL_DEGRADATION.md) · [Русский](GRACEFUL_DEGRADATION.md) · [中文](../zh/GRACEFUL_DEGRADATION.md)

> Версия 3.5.0. Что делает код, когда компонент отсутствует. В этой кодовой базе
> нет нумерованной модели «уровней деградации» — только откаты, описанные ниже.

## 1. Три исхода

| Исход | Как это видно |
|---|---|
| **Полный ответ** | обычный результат |
| **Ответ с дырами** | результат плюс список `degraded: [...]` (в `investigate`) или строка предупреждения |
| **Отказ** | JSON-конверт ошибки: `{"ok": false, "error": {"code", "message", "next_action", "details"}}`. В `details` сохранены прежние поля: `status` (`error`/`warning`/`timeout`), `detail`, `latency_ms`, `tool`, `recoverable` |

Правило: *вторичный* канал может тихо упасть (он не должен утаскивать ответ за
собой); *основная* возможность падает громко, со статусом, по которому вызывающий
может ветвиться.

## 2. Лестница поиска (дефолтная text-first конфигурация)

`MSCODEBASE_DENSE_OFF=true` и `MSCODEBASE_SQLITE_CHUNKS=true` — это дефолты:

```
SQLite FTS5 / BM25 → optional graph bucket → on-demand cosine rerank (top-N)
                   → exact-name boost → dedupe
```

| Отсутствующий компонент | Поведение | Где |
|---|---|---|
| Эмбеддер | кандидаты всё равно приходят из FTS5 + графа; on-demand реранк выбрасывает исключение, оно перехватывается, и объединённый пул возвращается без изменений | `engine.py::_apply_ondemand_reranker_async` |
| Реранкер (BGE / multi-provider) | порядок RRF возвращается как есть; `is_available == False` обрывает путь до любого вызова | `engine.py::_apply_multi_reranker_async` |
| Граф БД | графовая корзина ничего не даёт; текстовые результаты не затронуты | `_sqlite_hybrid_search_async` (этап графа обёрнут в `try/except`) |
| Хранилище чанков SQLite (инициализация упала) | записывается предупреждение, `_chunk_store = None`; уровень FTS5 пропускается, и вызов проваливается дальше к графу / BM25 (и dense, если включён) | `Searcher.__init__`, `hybrid_search_async` |
| Идёт переиндексация | синхронный путь возвращает **пустой результат немедленно** вместо блокировки на лок-объектах БД; асинхронный путь выбрасывает «повторите через несколько секунд» | `_reindex_fast_fail()`, `hybrid_search_async` |

Пустой ответ во время переиндексации сделан намеренно, но выглядит как «нет
совпадений», поэтому перед выводом, что запрос плохой, проверьте
`codebase(action="index", path="progress")`.

## 3. Устаревший dense-путь (`dense_off=false`)

`fast` эмбеддит запрос; если эмбеддер бросает исключение, `query_vector`
становится `None`, и вызов продолжается на FTS5 + графе (E24: незащищённый embed
раньше падал 10/10, пока `quality` деградировал). `quality` добавляет этап
реранкера, который пропускается, когда ни один провайдер не отвечает. Dense-поиск
— улучшение, никогда не предварительное условие.

## 4. `investigate` — деградация по каналам

Семь каналов в два прохода, таймауты на канал (12 s, 15 s для grep; весь
инструмент 30 s). Проход 1: `search`, `symbols`, `grep`. Проход 2: `impact`,
`graph`, `tests`, `memory`. Таймаут добавляет `name:timeout`; исключение
добавляет `name:<ExceptionType>`. Объединённый ответ всё равно возвращается и
ранжируется по `(channel count, rank)`, но вы всегда видите, какие каналы молчали:

```
🧭 investigate: `who calls ack_impact`
   identifiers: ack_impact
   results: 6 | degraded: tests:TimeoutError
```

### Доказательство, а не уверенность

`grep` — единственный канал, который может сказать «этот идентификатор встречается
в этом файле». Остальные всегда отвечают соседями, поэтому в шапке стоит точное
число совпадений по каждому идентификатору — и отдельное предупреждение, когда
самого субъекта в коде нет:

```
🧭 investigate: `where is build_call_graph defined`
   identifiers: build_call_graph, defined
   results: 8
   exact: build_call_graph=30, defined=20
```

```
🧭 investigate: `where is missing_widget implemented`
   identifiers: missing_widget, implemented
   results: 8
   ⚠️ exact: missing_widget=0, implemented=5 — the first identifier does not occur
   in the indexed code; the results below are neighbours, not matches.
```

Четыре правила, которые обязаны оставаться верными (guard:
`tests/test_no_silent_success.py`):

1. пустая популяция — это отказ (`exit 2`, причина в stderr), а не строка «0 %»;
2. упавший канал назван в `degraded`, и его молчание никогда не превращается в
   «0 совпадений» — молчание не является измерением;
3. `latency_ms` берётся с часов: вызов на 60 ms отдаёт не меньше 50, а две разные
   стоимости дают два разных числа;
4. совпадение двух неточных каналов на одном месте — корреляция, а не
   доказательство: строка `exact:` от согласия не меняется.

Если первый идентификатор не встречается **нигде** и граф не знает такой символ,
ответ — отказ, а не список соседей:

```
🧭 investigate: `where is missing_widget defined`
   identifiers: missing_widget
   results: 0
   exact: missing_widget=0
   ℹ️ Ничего не найдено. Запрос не подтверждён ни одним каналом.
   Neighbours withheld: 8. Pass include_neighbours=true to see them anyway.
```

`include_neighbours=true` возвращает их. Два случая отказа не дают: канал, который
не завершился (его молчание — «неизвестно», а не «нет»), и символ, известный графу
(имя реально, даже если точный канал его пропустил).

## 5. Отказы и таймауты на уровне инструмента

`@error_boundary(name, timeout_ms=...)` — единственная обёртка:

- таймаут — это настоящий `asyncio.wait_for` — зависшая корутина отменяется;
- **повторяются только таймауты** (с интервалом 1 s). `ToolError` детерминирован
  и возвращается сразу; неожиданное исключение логируется с traceback и
  возвращается как `INTERNAL_ERROR` с санитизированным сообщением (абсолютные пути
  заменены, длина ограничена 200 символами);
- бюджеты: 30 s для `write` и `investigate`, 45 s для `get_health_report`,
  300 s для `dual_arm_health_check`;
- каждый вызов записывается для `intel_tool_health` / `get_tool_metrics_summary`,
  включая падения, поэтому канал, который всегда падает, виден как статистика.

### Контракт ошибок (breaking change, 2026-11-08)

Любой отказ возвращает JSON-текст, а не Markdown-блок:

```json
{"ok": false,
 "error": {"code": "INDEX_NOT_READY",
           "message": "Index is not ready",
           "next_action": "Index is empty or building. Call intel_trigger_reindex(mode='incremental') …",
           "details": {"status": "warning", "tool": "search_code",
                       "detail": "Run index_project_dir() to initialize",
                       "latency_ms": 12, "recoverable": true}}}
```

`code` — одно из `VALIDATION_FAILED`, `NOT_FOUND`, `AUTH_REQUIRED`, `TIMEOUT`,
`RATE_LIMIT`, `INDEX_NOT_READY`, `REINDEX_IN_PROGRESS`, `DEPENDENCY_DOWN`,
`CONFLICT`, `INTERNAL_ERROR` (`src/core/error_envelope.py`). Ветвитесь по `code`;
читайте `next_action` вместо собственной стратегии повтора. Словарный результат
с ошибочным `status` (`error`, `warning`, `denied`, `too_large`, `not_installed`)
превращается в тот же конверт — он больше не может выглядеть как успешный
«✅ Completed».

`isError` для таких payload'ов — `true`: `src/mcp/error_results.py` один раз
оборачивает низкоуровневый CallTool-обработчик (устанавливается в
`create_mcp_server`) и поднимает флаг, если текст результата — ровно конверт;
сам текст не меняется, поэтому `json.loads(content[0].text)` продолжает
работать. Если будущий релиз `mcp` изменит эту приватную поверхность,
`tests/test_mcp_is_error.py` упадёт, а флаг деградирует в `false` с записью в
лог, но payload не будет испорчен.

Inline- и dev-инструменты (`generate_docs`, `bump_version`, `auto_update_docs`,
`install_git_hooks`, `refresh_db_connection`) отдают тот же конверт вместо
прежних рукописных строк `Error: …` / `❌ …`, поэтому флаг работает и у них.

## 6. Индексация

- **Только текст (по умолчанию)** — `index_project()` уходит в
  `_index_text_only_project()`: разбор, нарезка на чанки, запись в SQLite,
  обновление графа. Эмбеддер не вызывается.
- **Dense (`dense_off=false`)** — эмбеддер обязателен. `is_ready()` == false
  прерывает работу с «Embedder not ready. Indexing aborted.»; провайдер,
  вернувший неверное число векторов, прерывает пакет, а не пишет полуиндекс.

Отсутствующая грамматика Tree-sitter деградирует один язык, а не прогон:
`parser.py` импортирует каждую грамматику в собственном `try/except ImportError`.

## 7. Провайдеры

`RemoteEmbedder.mode` ∈ `onnx`, `onnx_server`, `lm_studio`, `ollama`,
`llama_cpp`, `fallback`, `unknown`. При старте ставится `fallback`, когда никто не
отвечает («безопасный дефолт — не притворяться, что ONNX работает»); сканер
перепроверяет с backoff (база 30 s, потолок 300 s). llama.cpp embed делает 3
повтора пакета с backoff, затем повторы по чанкам, затем выбрасывает исключение —
он не выдумывает нулевые векторы. Реранкеры (LM Studio, Ollama, llama.cpp,
HTTP ONNX) проверяются при инициализации; если все недостижимы,
`is_available == False` и действует порядок RRF. Опциональный ONNX-сервер — это
подпроцесс на `127.0.0.1:1235` (`DISABLE_ONNX_FALLBACK=true` убирает его).

## 8. LSP и сеть

Инструментам `lsp_*` нужен `basedpyright-langserver` в `PATH`. Без него каждый
возвращает «LSP недоступен (basedpyright не найден). …» и указывает на индекс
символов; неудачный запуск кешируется с TTL и перепроверяется, поэтому установка
basedpyright позже не требует постоянного перезапуска. Сам мост LSP→MCP был
удалён 2026-07-20, и ни один инструмент от него не зависит.

Ничто в дефолтном пути не использует сеть. Исключения включаются явно:
скачивания в `install.py` (всегда со спросом) и опциональный
`tree-sitter-language-pack`, чьи дополнительные парсеры скачиваются при первом
использовании.

## 9. Что **не** деградирует

«Плавно» здесь означало бы «молча и неправильно»:

| Ситуация | Ответ |
|---|---|
| Пустой индекс (`total_chunks == 0`) | `IndexNotReadyError` → `🟡 Warning: Index is not ready`, а не «нет результатов» |
| Запись в несущий файл без ack | `denied` от `modification_guard`, с impact-токеном |
| Неоднозначный символ для записи | `denied`, список кандидатов, без молчаливого выбора |
| Деструктивное действие вне доверенного корня | отказ по политике `trust_boundary` |
| `execute_script`, когда он не включён | инструмент вообще не регистрируется |
| Нарушение песочницы в `execute_script` | `SandboxViolation` до исполнения |

## 10. Как наблюдать деградацию

1. `get_health_report()` — индекс, провайдеры, ресурсы, предупреждения о памяти.
2. `codebase(action="index", path="status")` — `total_chunks`, файлы.
3. `get_runtime_counters()` — причины `verdict_blocked_*`; `blocked > 5%` от
   проверок — документированный сигнал посмотреть на архитектуру.
4. `intel_tool_health()` (полный профиль) — доля успеха, P50/P95, доля повторов.
5. `degraded[]` в `investigate` — сбои каналов на конкретном вызове.
6. `get_logs()` — недавние предупреждения/ошибки; полезная нагрузка остаётся в
   логах, а не в ответах.

---

**Verified against:** `src/core/search/engine.py` (tier order, rerank fallbacks,
`_reindex_fast_fail`), `src/core/error_handler.py` (`error_boundary`, retry
policy, `_format_error_response`, `IndexNotReadyError`, message sanitising),
`src/mcp/tools/base.py` (`require_index` → `IndexNotReadyError`),
`src/mcp/tools/investigate_tool.py` (7 channels, timeouts, `degraded`),
`src/core/indexing/indexer.py` (`index_project` → text-only),
`src/core/indexing/index_project_runner.py` (abort on embedder failure),
`src/core/indexing/index_pipeline.py`, `src/core/indexing/parser.py`,
`src/providers/embedder/remote_embedder.py`,
`src/providers/reranker/multi_provider.py`,
`src/providers/reranker/llama_runner.py`, `src/mcp/tools/lsp_tools.py`,
`src/core/lsp_client.py`, `src/mcp/tools/system_tools.py`,
`src/core/runtime_coordinator.py`, `src/config/settings.py`,
`src/core/error_envelope.py`.
