# KNOWN ISSUES — Архив 2026-07

> Перенесено из KNOWN_ISSUES.md 2026-08-29 по §4.8 R4 (Monthly Rotation)
> Оригиналы в git history: commit log по D:/Project/MSCodeBase/KNOWN_ISSUES.md

---


---

## Tech Debt (from Project Memory)

| ID     | Область         | Описание                                                                                                                                                            | Приоритет        |
| ------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| TD-001 | SymbolIndex     | SymbolIndex реализован частично; CI не покрывает lance-based индекс.                                                                                                | Medium           |
| TD-005 | llama_runner.py | **Осознанный техдолг:** 1515 строк, один связный класс `LlamaRunner`. Декомпозиция через миксины ухудшит архитектуру. Решение: не резать, зафиксировано 2026-07-18. | Low (осознанный) |
| CI     | Testing         | Нет полного прогона тестов с lancedb/tree-sitter в GitHub Actions                                                                                                   | High             |

## Current Model Stack (2026-07-17)

| Модель                        | Размер | Dim  | Vocab  | Скорость   | Статус     |
| ----------------------------- | ------ | ---- | ------ | ---------- | ---------- |
| `multilingual-e5-small-int8`  | 113 MB | 384  | 250002 | 37-52 ch/s | ✅ Активна |
| `reranker-bge-reranker-v2-m3` | 544 MB | 1024 | —      | —          | ✅ Активен |

## 2026-07-19 — deprecated create_index() in test_lancedb_race.py

**Status:** 🟡 OPEN — тесты проходят через deprecated path
**Risk:** Низкий — deprecated API всё ещё работает, но при обновлении lancedb может сломаться.
**Fix:** Переписать на `config=IvfPq(...)` при следующем touches к файлу.

## 2026-07-19 — Index corruption: 27330 chunks vs 4263 expected (FIXED)

**Status:** ✅ FIXED — Full reindex completed via `intel_trigger_reindex`
**Root cause:** LanceDB accumulated 1936 manifest versions with stale fragments. Repeated incremental reindexes without cleanup caused duplicate accumulation. File guard allows 366 indexable files; fallback chunker creates ~8 chunks/file for non-parseable extensions (.json, .yaml, .md, etc.) = ~2928 expected, but got 31592.
**Fix:** Full reindex cleared all fragments, rebuilt clean index. Post-fix: 4263 chunks, 303 files, 5514 symbols.
**Verification:** `search_code(quality)` now returns results (was 0), all 527 tests pass.

## 2026-07-19 — graph.py get_edge_stats indentation (FIXED)

**Status:** ✅ FIXED — commit `26258a9f`
**Root cause:** Метод был вложен внутрь `get_node_stats` (8 spaces вместо 4) после fix_indent4.py.
**Fix:** Убран 1 уровень отступа у `def get_edge_stats` и docstring.

## 2026-07-19 — test_suppression_markers fails (3 results instead of 1)

**Status:** 🟡 OPEN
**Symptom:** `test_suppression_markers` ожидает 1 SARIF result, получает 3.
**Risk:** Низкий — suppression logic работает, но тест написан для идеального case.
**Fix:** Нужно адаптировать тест или поправить suppression detection для multi-function файлов.

## 2026-07-19 — Missing MCP tools in server.py

**Status:** ✅ FIXED — Variant B (standalone @mcp.tool registration)
**Missing:** `notify_change`, `read_live_file`, `ack_impact`, `get_logs`, `get_health_report`.
**Fix:** Зарегистрированы как самостоятельные `@mcp.tool()` в `src/mcp/server_tools.py`
(`_register_inline_tools`), помимо существующих hub-мета-инструментов
(`index`/`system`/`write`). Использован `.__wrapped__` для обхода двойного
error_boundary (как в meta_tools.py). Теперь доступны напрямую и через hub.
**Impact:** `notify_change` P0 — workflow edit→notify→reindex теперь доступен напрямую.

## 2026-07-19 — graph.py get_edge_stats indentation (FIXED)

**Status:** ✅ FIXED — commit `26258a9f`
**Root cause:** Метод был вложен внутрь `get_node_stats` (8 spaces вместо 4) после fix_indent4.py.
**Fix:** Убран 1 уровень отступа у `def get_edge_stats` и docstring.

## 2026-07-19 — test_suppression_markers fails (3 results instead of 1)

**Status:** 🟡 OPEN
**Symptom:** `test_suppression_markers` ожидает 1 SARIF result, получает 3.
**Risk:** Низкий — suppression logic работает, но тест написан для идеального case.
**Fix:** Нужно адаптировать тест или поправить suppression detection для multi-function файлов.

---

## 2026-07-20 — `from src.lsp_main import server` ModuleNotFoundError ×695 (FIXED)

**Symptom:** `WatcherStatusTool._check_lsp_import()` и `ReadLiveFileTool.execute()` импортировали `src.lsp_main` при каждом вызове (каждые 20-30 сек). Лог: 695 ошибок `ModuleNotFoundError`. RAM росла +13-26 MB/мин.

**Root Cause:** `src.lsp_main` удалён из кодовой базы, но код `system_tools.py` не обновлён.

**Fix:** `_check_lsp_import()` → return False (без try/import). `ReadLiveFileTool` → читает только с диска, без LSP fallback.

**Файлы:** `system_tools.py` (WatcherStatusTool._check_lsp_import, ReadLiveFileTool.execute)

**Status:** ✅ FIXED — commit pending

**Guard:** при следующем Reload Window ошибки исчезнут из лога

---

## 2026-07-20 — `get_logs` MCP всегда пустой (FIXED)

**Symptom:** `get_logs()` возвращал "Logs clean — no errors" при 695+ реальных ошибках.

**Root Cause:** `get_recent_errors()` искал `{project}.log` (MSCodeBase.log), реальный лог — `mscodebase-intelligence.log`.

**Fix:** Заменить `f"{project_path.name}.log"` на `MAIN_LOG_FILE`.

**Файлы:** `log_manager.py` (get_recent_errors)

**Status:** ✅ FIXED

---

## 2026-07-20 — Contradiction Ledger TypeError: takes 0 positional arguments but 1 was given (FIXED)

**Symptom:** `run_contradiction_ledger()` вызывался с `_proj` (project_root), но не принимал параметров.

**Root Cause:** Сигнатура без `project_root` параметра, хотя `server_factory.py`/`main.py` передают `PROJECT_ROOT`.

**Fix:** Добавить `project_root: Optional[Path] = None`. При переданном пути — переопределяет глобальные ROOT и DIARY.

**Файлы:** `scripts/verify_diary.py`

**Status:** ✅ FIXED

---

## 2026-07-20 — DEV_DIARY.md дублирует AGENT_DIARY.md (нарушение §4.7)

**Symptom:** В проекте два дневника: `AGENT_DIARY.md` и `DEV_DIARY.md`. Оба содержат записи про Contradiction Ledger.

**Root Cause:** Исторически сложилось два параллельных дневника.

**Решение (§4.7):** Выполнено 2026-08-03: все 28 записей DEV_DIARY.md (2026-07-17..07-19) перенесены в AGENT_DIARY.md (сжатый формат §4.8, 3 хронологических блока). DEV_DIARY.md — редирект `# ARCHIVED — см. AGENT_DIARY.md`. Дубль записи про multilingual-e5-small-int8 НЕ перенесён (уже была в AGENT_DIARY как [2026-07-17 20:00]).

**Status:** ✅ CLOSED (2026-08-03)

---

## 2026-07-20 — `search_code` quality mode: холодный старт Reranker (KNOWN)

**Symptom:** Первый вызов `search_code(mode="quality")` после перезагрузки MCP падает с "Context server request timeout". Второй и последующие — работают (816ms).

**Root Cause:** `ensure_reranker_started()` в `llama_runner.py` может пытаться СТАРТОВАТЬ llama-server с `--reranking` флагом, что занимает ~2-3s. `@error_boundary(timeout_ms=15000)` + sync `search_with_mode` + `asyncio.wait_for` не прерывает синхронный код.

**Fix:** Прогрев reranker при старте MCP (уже есть `_start_llama_sync()`). Альтернатива: сделать `search_with_mode` async.

**Status:** 🟡 OPEN — известная проблема, workaround: 2-й вызов работает

---

## 2026-07-20 — `error_boundary` sync_wrapper: run_until_complete внутри работающего loop (TECH DEBT)

**Symptom:** `error_boundary` для синхронных функций (типа `search_with_mode`) использует `asyncio.get_event_loop().run_until_complete()` внутри уже работающего event loop — потенциальный RuntimeError.

**Fix:** Заменить на `asyncio.to_thread()` в async-контексте.

**Status:** 🔴 OPEN — может вызывать скрытые крахи

---

## Current Model Stack (2026-07-20)

| Модель                        | Размер | Dim  | Скорость      | Место                 | Статус     |
| ----------------------------- | ------ | ---- | ------------- | --------------------- | ---------- |
| `multilingual-e5-small-int8`  | 113 MB | 384  | 37-52 ch/s    | ONNX внутри процесса  | ✅ Активна |
| `reranker-bge-reranker-v2-m3` | 544 MB | 1024 | ~472ms/4docs  | llama-server (8081)   | ✅ Активен |

## Process Architecture (зафиксировано 2026-07-20)

| Процесс | Роль | Память | Путь |
|---------|------|--------|------|
| `venv\Scripts\python.exe` | **Launcher** (0.6MB всегда) | 0.6 MB | Расширение |
| `C:\Python314\python.exe` | **MCP-worker** (реальный) | 200-2000 MB | Система |
| `llama-server.exe` | **Reranker** | 60-900 MB | Порт 8081 |

> Launcher (0.6MB) запускает `C:\Python314\python.exe -m src.main` через install.py.
> Оба видны в Диспетчере задач под ОДНИМ узлом (parent-child).

---

## 2026-07-20 — 5 MCP-инструментов без ограничения вывода (DEFERRED)

**Symptom:** При аудите 40+ инструментов выявлено 5, где объём возвращаемых данных
не ограничен — могут вернуть весь проект целиком.

| # | Tool | Файл | Проблема | Приоритет |
|---|------|------|----------|-----------|
| 1 | **ImpactAnalysisTool** | search_tools.py | callers/callees/affected_files — всё без limit | 🔴 4/5 |
| 2 | **CrossProjectDepsTool** | graph_tools.py | affected проекты — список без limit | 🔴 3/5 |
| 3 | **intel_get_project_context** | server_tools.py | env vars + health.lists — нет фильтра | ⚠️ 2/5 |
| 4 | **GetRepoMapTool** | analysis_tools.py | все файлы проекта — нет max_files | ⚠️ 2/5 |
| 5 | **GraphQueryTool** feature | graph_tools.py | files/symbols — без limit | ⚠️ 2/5 |

**Fix (рекомендованный):** Добавить параметры `max_items`/`max_files`/`limit` с разумными
значениями по умолчанию (30-50), добавить `truncated: true` флаг.

**Root Cause:** Исторически все инструменты проектировались без ограничения вывода.
Проблема не проявлялась на малых проектах, но с ростом индекса (4000+ chunks)
становится критичной — ImpactAnalysisTool может вернуть callers/callees для всего проекта.

**Status:** 🔴 DEFERRED — по просьбе владельца записано на будущее

## 2026-07-21 — ADR auto-collect on startup (ИСПРАВЛЕНО)

**Что было:** `intel_get_project_memory()` возвращал пустой результат на старте.
Требовался ручной вызов `intel_auto_collect_adrs()`.

**Fix:** В `_register_intelligence_tools()` (server_tools.py) добавлен автоматический
вызов `intel_layer.intel_auto_collect_adrs(max_commits=100)` сразу после создания слоя.
Обёрнут в try/except — не блокирует старт.

**Попутно:** Очищены все лог-файлы (mcp_global.log, mscodebase-intelligence.log и их ротации,
crash_debug.log, llama_reranker_stderr.log) — 738 ошибок убрано.

**Status:** ✅ FIXED — требуется перезагрузка Zed для активации.

## 2026-07-21 17:30 — АУДИТ ФИНАЛ: audit.md очищен от B1-B12 + эксперименты 553 passed

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. **audit.md обновлён:** секция багов B1-B12 заменена на статус "✅ Все исправлены" с таблицей фиксов
2. **Эксперименты проведены:** 5 экспериментов по валидации всех B1-B12
   - Expe...
- **Статус:** автоматически синхронизировано


## 2026-07-21 17:00 — ФИНАЛ: verify_diary 89% + B10/B11 closed + SymbolCache MCP tools + 3 commits push

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. **SymbolCache расширен:** парсинг `tool_name="..."` для class-based MCP tools (graph_query, get_symbol_info, codebase, git и др.)
2. **Stdlib stoplist дополнен:** `tool`, `warning`...
- **Статус:** автоматически синхронизировано


## 2026-07-21 08:30 — СЕССИЯ ЗАКРЫТА: audit полный цикл + internet research + финал

- **Источник:** AGENT_DIARY.md
- **Описание:** **Итог сессии:**

| Этап | Задача | Статус |
|------|--------|--------|
| 1 | 12 багов B1-B12 из experiments/audit.md | ✅ Исправлено |
| 2 | 10 pre-existing test failures | ✅ 541 passed, 0 failed |
| ...
- **Статус:** автоматически синхронизировано


## 2026-07-21 07:55 — Чистка корня репозитория (audit recommendation)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**

| Действие | Файл | Результат |
|----------|------|-----------|
| 🗑️ Удалён | `nul`, `results.sarif`, `temp_settings.json`, `zed_settings.json` | Stale артефакты |
| 🗑️ Удалён | `cra...
- **Статус:** автоматически синхронизировано


## 2026-07-21 00:30 — AUDIT FIX: 12 замечаний из experiments/audit.md (B1-B12)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Источник:** `experiments/audit.md` — полный разбор + сравнение с аналогами.

**Что сделано (по приоритетам):**

### 🔴 CRITICAL / HIGH (B1-B4) — runtime-баги

| # | Файл | Суть | Фикс |
|---|------|-...
- **Статус:** автоматически синхронизировано


## 2026-07-20 19:55 — АРХИТЕКТУРА MCP: ДВА связанных процесса + ROOT CAUSE `Not found`

- **Источник:** AGENT_DIARY.md
- **Описание:** **ВАЖНО (зафиксировано от пользователя, больше не путать!):**
MCP запускается КАК ДВА связанных процесса (parent-child), оба пишут в ОДНУ LanceDB:
1. `C:\Users\misha\AppData\Local\Zed\extensions\mscod...
- **Статус:** автоматически синхронизировано


## 2026-07-20 18:20 — FTS5 visibility: маркер source + fast-mode integration

- **Источник:** AGENT_DIARY.md
- **Описание:** **Проблема (от пользователя):** FTS5 работает, но в выдаче `search_code` не видно,
что результат от FTS5. И вообще — что ещё не до конца подключено?

**Что нашёл:**
1. `format_search_code` НЕ выводил ...
- **Статус:** автоматически синхронизировано


## 2026-07-20 22:45 — Системный фикс: 3 бага (lsp_main, get_logs, contradiction ledger) + архитектурная диагностика

- **Источник:** AGENT_DIARY.md
- **Описание:** **Контекст:** Пользователь перезагрузил MCP, потребовал полную диагностику по протоколу А-Б-В
после жалоб на `search_code` таймауты, `get_logs` пустоту и невидимость FTS5.

**Проверка инструментов (А→...
- **Статус:** автоматически синхронизировано


## 2026-07-20 18:05 — notify_change: root cause таймаута (blocking event loop)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** `notify_change` возвращал «Context server request timeout»; при
повторных вызовах весь MCP переставал отвечать даже на `debug_runtime_passport`.

**Root Cause (§5.16 / async):** `NotifyCh...
- **Статус:** автоматически синхронизировано


## 2026-07-18 23:00 — verify_diary.py: Ledger-проверка diary ↔ reality (DEV EXP.md §9)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:** Расширен `scripts/verify_diary.py` — добавлена §7.7 проверка
(`verified_from_clean_state`), `--interactive` и `--fix-missing` CLI флаги.

**Результат首次 запуска на реальном diary (3491...
- **Статус:** автоматически синхронизировано


## 2026-07-19 21:30 — Variant B: 5 MCP tools as standalone @mcp.tool() (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:** Зарегистрировал 5 инструментов как самостоятельные `@mcp.tool()`
в `src/mcp/server_tools.py` (`_register_inline_tools`), помимо существующих
hub-мета-инструментов (`index`/`system`/`w...
- **Статус:** автоматически синхронизировано


## 2026-07-19 22:10 — zed_config.py: безопасная перезапись (merge-only)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Проблема (до):** `patch_zed_settings` делал `json.loads` после срезки `//`
комментов. При trailing comma / `/* */` блоке (валидный JSONC в Zed) парсер
падал → `settings = {}` → **полная перезапись ф...
- **Статус:** автоматически синхронизировано


## 2026-07-19 22:25 — Docs: обновлены под zed_config.py safe-merge

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:** проверил docs на старые/неверные пути конфигурации.
- `extensions/installed/...`, `ZED_CONFIG_DIR`, `~/Library/Application Support/Zed`
  (как неверный), `~/.zed` — в docs НЕ найдены ...
- **Статус:** автоматически синхронизировано


## 2026-07-19 22:40 — LLAMA_CPP_ENABLED toggle + is_compatible fix

- **Источник:** AGENT_DIARY.md
- **Описание:** **Контекст:** пользователь сказал llama.cpp embedder «пока отключён» —
нужен тумблер по протоколу §2 (Tumbler). Попутно нашёлся баг: `is_compatible`
импортировался из `llama_runner.py`, хотя определён...
- **Статус:** автоматически синхронизировано


## 2026-07-18 19:10 — Contamination check rewrite + verified_from_clean_state

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** Старый contamination-check сравнивал intra-thread (разные темы) vs
cross-thread (одна тема с разным префиксом) — измерял тематическое сходство,
а не контаминацию. Порог 0.5→0.98 был подго...
- **Статус:** автоматически синхронизировано


## 2026-07-18 17:30 — AsyncInferQueue race condition: фикс + тест на смешение векторов

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** Claude-аудит нашёл новую гонку в AsyncInferQueue (коммит e34d5e1):
`self._ov_results` — общий dict на весь процесс, concurrent embed_batch() перезаписывают
вектора друг друга. Не нули (sh...
- **Статус:** автоматически синхронизировано


## 2026-07-18 17:00 — Architecture Review: все 8 проблем закрыты

- **Источник:** AGENT_DIARY.md
- **Описание:** **Коммиты (по протоколу, каждый шаг — отдельный):**

| Коммит    | Проблема            | Что сделано                                                            |
| --------- | ------------------- | --...
- **Статус:** автоматически синхронизировано


## 2026-07-18 16:30 — Architecture Review: 8 проблем от Claude-аудита

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** Claude-аудит выявил 8 проблем (3 P0, 3 P1, 2 P2).

**Что сделано:**

| P   | Проблема                                                                    | Коммит  | Статус   |
| --- | ---...
- **Статус:** автоматически синхронизировано


## 2026-07-18 16:00 — ГЛУБОКИЙ АУДИТ: каждая строка README через grep (итерация 2)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** После первого аудита остались ошибки: Project Structure (12 багов),
3 пропущенных tools, 3 бага в Documentation Map, переводы ru/zh рассинхронизированы.

**Что сделано (5 параллельных ауд...
- **Статус:** автоматически синхронизировано


## 2026-07-18 15:30 — ПОЛНЫЙ АУДИТ ДОКУМЕНТАЦИИ И МЁРТВОГО КОДА

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** Документация ушла от реальности — числа инструментов, имена классов, env-переменные. Мёртвый код ~2000+ строк.

**Аудит (4 параллельных агента):**

1. docs/ (~59 файлов): 2 критических ра...
- **Статус:** автоматически синхронизировано


## 2026-07-18 15:00 — ПОЛНЫЙ АУДИТ: рассинхрон install/docs vs runtime

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** После перескачивания `main` обнаружено, что финальный отчёт предыдущей сессии не совпадает с реальным состоянием кода.

**Найдено 5 проблем:**

1. **Пул InferRequest отсутствует** — заявл...
- **Статус:** автоматически синхронизировано


## 2026-07-17 23:00 — СЕССИЯ ЗАКРЫТА: Explainability + IMPORTS + Drift Detector

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано за сессию (5.5ч):**

1. **R&D**: Исследовано 35+ файлов, 5 прототипов, сравнение с 15 внешними инструментами
2. **Explainability Layer**: SearchTracer + ChunkTrace (357 строк). `search_c...
- **Статус:** автоматически синхронизировано


## 2026-07-17 20:00 — SWITCH TO multilingual-e5-small-int8 + batch optimization

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** После исправления INT8 модели (cos=1.0) скорость оставалась 18 ch/s,
хотя бенчмарки small INT8 показывали 41-52 ch/s.

**Root Cause:**

1. `indexer.py` `_BATCH_SIZE=64` — неоптимально для...
- **Статус:** автоматически синхронизировано


## 2026-07-17 19:00 — FULL INVESTIGATION: INT8 broken vocab, requantization, cleanup

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** search_code(mode=fast) возвращал мусор. INT8 модель не совпадала с FP32 (cos≈0).

**Root Cause:** `e5-base-v2-int8/model_quantized.onnx` был сквантизирован ИЗ НЕВЕРНОЙ БАЗОВОЙ МОДЕЛИ:

- ...
- **Статус:** автоматически синхронизировано


## 2026-07-16 21:50 — Fix: MCP server crash при старте (path с \n)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** MCP-сервер падал через 2 сек после запуска, 120MB RAM

**Root Cause:** В SQLite БД Zed поле `paths` содержит 2 пути через `\n`:

- `C:\Users\misha\Downloads\Project Remaining Tasks Review...
- **Статус:** автоматически синхронизировано


## 2026-07-16 22:00 — Fix llama_runner.py: 8 bare except

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** #2 hotspot — 10 bugs (score 0.50)

**Что сделано:**

- **8 bare except** — `logger.warning("exception", exc_info=True)` заменены на
  контекстные сообщения (`f"stop kill: {_e}"`, `f"JobOb...
- **Статус:** автоматически синхронизировано


## 2026-07-16 22:15 — Fix intelligence/layer.py: 15 bare except + architecture test

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** #3 hotspot — 9 bugs (score 0.50)

**Что сделано:**

- **15 bare except** — `logger.warning("Exception suppressed at layer.py")` заменены на
  контекстные `f"Exception suppressed at layer....
- **Статус:** автоматически синхронизировано


## 2026-07-16 21:45 — Операция «Чистка remote_embedder.py»: 12 багов

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** `remote_embedder.py` — #1 hotspot с 13 bugs (score 0.50).

### Найденные баги

#### 🔴 Race Conditions (2 шт) — mode без _mode_lock

1. `_init_onnx` L664: `self.mode = "fallback"` без блок...
- **Статус:** автоматически синхронизировано


## 2026-07-16 21:15 — Фаза 2 завершена: Группировка Graph-тулов

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**

### 1. graph_query → единый мультиплексированный инструмент

Смержены 4 тула в один `graph_query(action=...)`:

| Было                                | Стало                         ...
- **Статус:** автоматически синхронизировано


## 2026-07-14 22:42 — Архитектурный аудит MCP vs IDE-Native + фикс bare except

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**

### 1. Сравнительный аудит MCP vs IDE-Native

- Запущен **двойной аудит**: Агент A (MCP) vs Агент B (grep/read_file/terminal)
- Замерены тайминги 8 операций, RAM, качество, полнота о...
- **Статус:** автоматически синхронизировано


## 2026-07-14 22:00 — FINAL: intel_auto_collect_adrs + MMR + Auto Intent + Synonyms

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**

### 1. intel_auto_collect_adrs — больше НИКОГДА не упадёт

- **subprocess полностью удалён.** Читаем `.git/logs/HEAD` + `.git/objects/X/XXXXX` через `open()` + `zlib.decompress()`.
-...
- **Статус:** автоматически синхронизировано


## 2026-07-14 18:40 — Fix intel_auto_collect_adrs: UnicodeDecodeError на русской Windows

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** `intel_auto_collect_adrs` падал с "Context server request timeout"
при каждом вызове. HEAD-фикс (asyncio.to_thread) не помогал.

**Root Cause:** `subprocess.run(..., text=True)` на русско...
- **Статус:** автоматически синхронизировано


## 2026-07-13 02:30 — Post-Mortem: FP32-priority regression + INT8 revert

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** После коммита `e7c61dc` скорость эмбеддинга упала с ~350 до ~9 ch/s.
`search_code(mode='fast')` возвращал `extension.toml`/`lsp_client.py` (score 0.0).

**Root Cause (первопричина):** Я (...
- **Статус:** автоматически синхронизировано


## 2026-07-13 19:30 — Fix: MAX_CHUNK_CHARS 2000→1800 + truncation logging + move experiment

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** E5-base имеет лимит 512 токенов, но `MAX_CHUNK_CHARS = 2000` позволяет чанкам до ~650 токенов. Также: обрезка чанков происходит молча (без логирования), и экспериментальный файл лежит в п...
- **Статус:** автоматически синхронизировано


## 2026-07-13 18:00 — Fix OPTIONAL MATCH silent data corruption + IS NULL bug + 47 tests

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** v3.2.0 Cypher Engine имеет 3 критических бага:

1. `OPTIONAL MATCH` полностью игнорируется в `translate()` — SQL генерирует только INNER JOIN, теряя данные
2. `WHERE v IS NULL/IS NOT NULL...
- **Статус:** автоматически синхронизировано


## 2026-07-12 23:40 — Close All Open Items: stale docs fix + async ADR + index recovery + terminal diagnosis

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** После docs-sync сессии (21:40) остались 4 открытых пункта:

1. MCP index 0 chunks (не подтверждён живой рантайм)
2. `intel_auto_collect_adrs` таймаут (blocking subprocess in async)
3. Sta...
- **Статус:** автоматически синхронизировано


## 2026-07-12 20:00 — Fix: symbol_index_count 0 vs 3197 (timing race)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** `intel_get_runtime_status` показывал `symbol_index_count: 0`, а `get_health_report` — `symbols: 3197` для одного проекта. Рассинхрон диагностики.

**Root Cause:** `_resolve_symbol_count()...
- **Статус:** автоматически синхронизировано


## 2026-07-12 19:55 — Fix: Watchdog "56 лет простоя" ложная critical при idle

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** `indexer.py:84` инициализировал `_watchdog_heartbeat = 0.0` (эпоха Unix 1970).
При idle `watchdog_status()` считал `age = time.time() - 0.0 ≈ 1.7e9 сек ≈ 56 лет`
→ `alive=False` → health_...
- **Статус:** автоматически синхронизировано


## 2026-07-13 — Producer-Consumer indexing + contextual chunks + thread safety

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

1. Индексация в 1 поток — 16% CPU, ~8 чанков/с (было 16.6%)
2. Hardcoded 1024-dim в schema/padding — при E5-base (768) тихо ломал поиск
3. Shared state без блокировок — race condition пр...
- **Статус:** автоматически синхронизировано


## 2026-07-13 — Post-migration hardening: 3 bug fixes + docs sync

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** После миграции на E5-base ONNX:

1. Reranker статус всегда 🔴 offline — баг `_find_pid()` (UnicodeDecodeError в netstat -ano)
2. E5 prefix double-adding при повторном вызове
3. Hardcoded п...
- **Статус:** автоматически синхронизировано


## 2026-07-12 — Великий Рефакторинг: BGE-M3 → E5-base ONNX

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** BGE-M3 через llama-server: нестабилен, 2 процесса, 18 i/s, 285 MB + VRAM.
E5-base ONNX: 265 MB CPU, 360 i/s, стабилен, 0 VRAM.

**Solution:**

1. Скачан E5-base ONNX INT8 (265 MB) из Hugg...
- **Статус:** автоматически синхронизировано


## 2026-07-13 — Session Close: Full audit, hardening, demo

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Сессия закрытия — проверено всё от установщика до финального коммита.

**Summary (3 commits, 32 files changed):**

**Commit 1** (`f0c4f09`):

- New MCP tool `get_variable_flow(name, scope...
- **Статус:** автоматически синхронизировано


## 2026-07-11 23:00 — Threads.db Research + edit_prediction 403 verdict

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Исследовать threads.db (39MB) для долговременной памяти и ошибку edit_prediction 403

**Findings:**

### threads.db — формат полностью расшифрован

- SQLite: `CREATE TABLE threads (id, su...
- **Статус:** автоматически синхронизировано


## 2026-07-11 22:30 — Docs: Synchronize ALL docs for v3.0 (write tools, LSP, meta-patching)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** 10 documentation files out of sync after Phases 1-3, P0 meta-patching, and bug fix.

**Solution:** Updated all 10 files:

- README.md (en/ru/zh): 50→56 tools, added Write Tools section/ta...
- **Статус:** автоматически синхронизировано


## 2026-07-11 17:30 — Fix: 3 production bugs (commit 48c2b28)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Stale indexer reference, fd leak in llama_runner, lazy Path imports.

**Solution:**

- `_resolve_active_indexer` — `registry.get_indexer(target)` с нормализованным путём
- `llama_runner.p...
- **Статус:** автоматически синхронизировано


## 2026-07-11 14:30 — Docs: Перевод 3 документов en → zh

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Нужно перевести 3 файла документации с английского/русского на китайский язык.

**Solution:**

- `docs/en/CONTRIBUTING.md` → `docs/zh/CONTRIBUTING.md` — перевод правил для контрибьюторов
...
- **Статус:** автоматически синхронизировано


## 2026-07-11 09:30 — Investigation: Почему ZED упал — Root Cause Analysis (OOM)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Zed Editor периодически падает (crash/restart). Пользователь запросил расследование.

**Investigation Findings:**

1. **Primary cause: OOM (Out of Memory)** — память Zed неоднократно дост...
- **Статус:** автоматически синхронизировано


## 2026-07-11 12:00 — Fix: документация испорчена — 7 проблем на главной странице

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- `docs/KNOWN_ISSUES.md` не существовал — битая ссылка на главной странице и в переводах
- `intel_execution_timeline()` дублировалась в Intel Layer (14) и Diagnostic (3)
- В перечислении...
- **Статус:** автоматически синхронизировано


## 2026-07-11 17:00 — Close all open items: remove Rust/WASM, clean KNOWN_ISSUES.md

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** все открытые пункты из KNOWN_ISSUES.md требовали закрытия.

**Solution:**

- Rust/WASM draft: директория extension/ удалена, комменты из extension.toml убраны
- LSP WONTFIX: убран из KNOW...
- **Статус:** автоматически синхронизировано


## 2026-07-11 12:15 — Hotfix: README.md был на русском вместо английского

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- Корневой README.md был перезаписан русским текстом в коммите v2.7.1 (bd46143)
- Клик по "🇬🇧 English" вёл на тот же русский файл (самоссылка)
- Русский язык в секциях: Quick Start, Trou...
- **Статус:** автоматически синхронизировано


## 2026-07-11 08:00 — Docs: синхронизированы китайские переводы (9 файлов)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- docs/zh/* (14 файлов) отставали от en-версий
- ARCHITECTURE.md: v2.4.4 вместо v2.7.0
- HANDFOFF.md: ~1600 chunks, LM Studio primary вместо llama.cpp
- CHANGELOG.md: без v2.7.1+
- FAQ.m...
- **Статус:** автоматически синхронизировано


## 2026-07-11 10:15 — Fix: get_status показывал 1 files | 1 symbols вместо реальных

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- `get_index_status()` показывал Files: 1 при реальных 170+ файлах
- `intel_get_runtime_status()` показывал Symbols: 1 (читал total_files вместо symbol_index_count)

**Root cause:**

1. ...
- **Статус:** автоматически синхронизировано


## 2026-07-11 02:30 — Docs audit: 7 файлов исправлено, 28 отмечено в KNOWNS_ISSUES.md

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- Claude review выявил расхождения docs vs code
- HANDFOFF: "~1600 chunks" — актуально ~3000
- ARCHITECTURE: версия 2.4.4 — актуально 2.7.0
- GRACEFUL_DEGRADATION: нет llama.cpp (4 уровн...
- **Статус:** автоматически синхронизировано


## 2026-07-11 02:15 — Fix: Полный аудит документации (61 файл)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- Claude review выявил расхождения docs vs code
- HANDFOFF: "~1600 chunks" — актуально ~3000
- ARCHITECTURE: версия 2.4.4 — актуально 2.7.0
- GRACEFUL_DEGRADATION: нет llama.cpp (4 уровн...
- **Статус:** автоматически синхронизировано


## 2026-07-11 01:45 — Fix: SQL ORDER BY + RRF docs → KNOWNS_ISSUES.md

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- Claude review нашел 2 бага: SQL query без ORDER BY (multi-window race), RRF псевдокод с неверным enumerate
- 61 markdown-файл документации — часть не синхронизирована с кодом

**Soluti...
- **Статус:** автоматически синхронизировано


## 2026-07-10 23:55 — Fix: Insider CRT API Set — патч PE-импортов api-ms-win-crt → ucrtbase

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**
На Windows Insider (build >= 26000, niki_v2) Microsoft удалила виртуальные
API Set DLL (api-ms-win-crt-*). Все MSVC-сборки llama.cpp (включая Vulkan
Clang build, где llama-server-impl.dll...
- **Статус:** автоматически синхронизировано


## 2026-07-10 23:40 — Fix: Windows Insider → Vulkan/Clang сборка (статический CRT)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**
Даже после фикса downlevel/ CRT DLL, llama-server.exe всё равно падал
с STATUS_DLL_NOT_FOUND. MSVC-сборка требует CRT API Set, которых нет на Insider.

**Root cause:**
На Windows Insider ...
- **Статус:** автоматически синхронизировано


## 2026-07-10 23:15 — Fix: llama.cpp не синхронизируется в папку расширения Zed

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**
`step_llama()` и `step_gguf()` в install.py скачивают бинарник и GGUF модели
в `_get_ext_dir()` (= PROJECT_ROOT), но НЕ копируют их в ZED_EXT_DIR.
MCP-сервер запускается из папки расширен...
- **Статус:** автоматически синхронизировано


## 2026-07-10 22:58 — Fix: llama.cpp не стартует на Windows Insider (STATUS_DLL_NOT_FOUND)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**
После загрузки MCP-сервера llama.cpp процессы (embed + reranker) не запускались.
`embedder_mode: unknown`, `embedder_available: ✗`.
В логах: `llama.cpp не найден за 30с`.

**Root cause:**...
- **Статус:** автоматически синхронизировано


## 2026-07-10 15:50 — Final Stress Test: All 33 tools verified, Qwen3 + BGE-M3 confirmed

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Финальная верификация производительности и стабильности MCP-сервера
после перехода на Qwen3-Embedding (ctx=1024) + BGE-M3 reranker через llama.cpp.

**Results (7 search_code calls, 0 erro...
- **Статус:** автоматически синхронизировано


## 2026-07-10 08:20 — Fix: Critical race condition in llama_cpp embed_batch + intel_get_runtime_status

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** `embed_batch` всегда возвращал нулевые векторы в режиме `llama_cpp`.
`intel_get_runtime_status` показывал `onnx` даже когда llama.cpp работал.

**Root Cause:**

1. `remote_embedder.py:651...
- **Статус:** автоматически синхронизировано


## 2026-07-09 21:20 — Feature: Добавлен IVF_PQ индекс в LanceDB для ускорения поиска

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Поиск по векторным индексам работает O(N) — полный перебор всех чанков.

**Solution:**

- Добавлен шаг 4 в `index_project()`: создание IVF_PQ индекса после завершения индексации
- Индекс ...
- **Статус:** автоматически синхронизировано


## 2026-07-09 23:30 — install.py: Qwen3 добавлен, resume баг починен

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** install.py качал BGE-M3 вместо Qwen3.
hf_hub_download(resume=True) не работает с huggingface_hub v1.20.1.

**Fix:**

- install.py step_gguf: qwen3-embedding → bge-m3 → reranker (приоритет...
- **Статус:** автоматически синхронизировано


## 2026-07-09 21:00 — Investigation: Полный аудит MCP, RAM, llama.cpp, Zed 1.10.0

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Комплексный запрос пользователя:

1. Проверить все MCP инструменты (таймауты)
2. Почему RAM выросла с 300MB до 1GB+
3. Вернуть reranking
4. Проанализировать Zed 1.10.0
5. Почему не работа...
- **Статус:** автоматически синхронизировано


## 2026-07-08 23:00 — Fix: ONNX model paths, shared cache, installer reliability

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Models existed at PROJECT_ROOT (543+544 MB) but were NOT copied to
ZED_EXT_DIR where MCP server searches for them. Embedder and reranker had no
fallback paths. Installer step_models didn'...
- **Статус:** автоматически синхронизировано


## 2026-07-07 23:45 — Fix: B1/B2/B3 peripheral bugs from forensic log analysis

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Анализ 16k строк логов выявил 3 редких бага:

- B1: `UnboundLocalError: raw` в SearchCodeTool (raw не assigned в deep/context/ask/auto)
- B2: `TypeError: object of type 'int' has no len()...
- **Статус:** автоматически синхронизировано


## 2026-07-07 22:00 — Fix: paranoid audit of search engine v2.6.0

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Проведён комплексный аудит поискового движка после ввода
Multi-Bucket RAG, SYSTEM_PROFILE и mode=ask. Найдены скрытые баги,
которые 391 юнит-тест не ловили.

**Critical bugs found:**

1. ...
- **Статус:** автоматически синхронизировано


## 2026-07-06 23:00 — Refactor: Полный pipeline реранкинга + телеметрия + memory safety

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- Реренкер вызывал LLM или embedding, не в цепочке
- LM Studio перезагрузка не отслеживалась
- Нет per-stage замеров времени
- Телеметрия не видела какая модель использовалась

**Solutio...
- **Статус:** автоматически синхронизировано


## 2026-07-06 19:00 — Fix: Translate Russian _() templates to English in search_tools.py and analysis_tools.py

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** `_(f"...")` pattern (f-string inside i18n) and Russian text in `_()` template strings — defeats i18n purpose.

**Solution:**

- `search_tools.py`: 8 calls fixed — translated templates to ...
- **Статус:** автоматически синхронизировано


## 2026-07-05 — UI Formatter: единый стиль вывода

- **Источник:** AGENT_DIARY.md
- **Описание:** Все 43 MCP-инструмента переведены на единый Markdown-формат через `ui_formatter.py`.

- Убран сырой JSON из intel_* инструментов
- Убран JSON-блок из `_format_success_response`
- `debug_runtime_passpo...
- **Статус:** автоматически синхронизировано


## 2026-07-05 — DebounceBatch deadlock (критический баг)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Проблема:** MCP-сервер зависал через ~5 секунд после пачки `notify_change`.
**Причина:** `await self._flush()` вызывался внутри `threading.Lock`.
`threading.Lock` не reentrant — второй захват блокир...
- **Статус:** автоматически синхронизировано


## 2026-07-05 — Определение проекта на Windows (ключевое открытие)

- **Источник:** AGENT_DIARY.md
- **Описание:** `ZED_WORKTREE_ROOT` и `current_dir` не работают на Windows (баг Zed #36019).
**Решение:** читать `active_workspace_id` из SQLite `scoped_kv_store`.
Приоритет 0 в `resolve_project_root()`. Работает на ...
- **Статус:** автоматически синхронизировано


## 2026-07-05 — LSP расследование (WONTFIX)

- **Источник:** AGENT_DIARY.md
- **Описание:** Исследованы исходники Zed, найдена первопричина: `mscodebase-lsp` не регистрируется
в `LanguageRegistry` Zed на Windows. `settings.json` не может зарегистрировать
новый LSP — только override пути для ...
- **Статус:** автоматически синхронизировано


## 2026-07-04 — Аудит и чистка проекта

- **Источник:** AGENT_DIARY.md
- **Описание:** - Найдено 19 архитектурных проблем (2 critical, 8 high, 7 medium, 1 low + 7 architectural)
- Удалено 6 позиций мусора: hybrid_server.py, backup-файлы, пустые директории
- Обновлены Skills в `.agents/s...
- **Статус:** автоматически синхронизировано


## 2026-07-19 23:25 — LLAMA_CPP_ENABLED=true + reranker online

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:** включён llama.cpp reranker (`bge-reranker-v2-m3`) через тумблер `LLAMA_CPP_ENABLED=true` (в `.env`).
- Порт 8081 (reranker) теперь поднимается при старте MCP.
- Модель `models/Bge-M3-...
- **Статус:** автоматически синхронизировано


## 2026-07-20 22:30 — PID-lock + self-healing + auto-index guard (Plane A→B complete)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. **IndexProjectRunner** — полный рефакторинг:
   - Удалён дублирующийся lock (db_manager уже имеет PID-lock)
   - Добавлен `db_manager` parameter для доступа к write lock / reset_co...
- **Статус:** автоматически синхронизировано


## 2026-07-21 00:15 — ADR auto-collect on startup + log cleanup

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** `intel_get_project_memory()` возвращал пустой результат на старте,
хотя в git-логе есть архитектурные решения. Логи содержали 738 ошибок.

**Root Cause:**
1. `intel_auto_collect_adrs` ник...
- **Статус:** автоматически синхронизировано

---

## 2026-07-18 — P0-3 AsyncInferQueue deadlock (INC-6DF5)

- **Источник:** docs/KNOWN_ISSUES.md (перенесено при слиянии)
- **Симптом:** AsyncInferQueue deadlock при 4+ concurrent embed_batch() вызовах.
- **Fix:** Variant B — threading.Lock вокруг submit+wait_all+collect.
- **Статус:** ✅ Fixed

## 2026-07-17 — INT8 model broken vocab (INC-VOCAB)
- **Симптом:** Cosine similarity INT8 vs FP32 = -0.03. Vocab 30522 вместо 250002.
- **Fix:** Смена на multilingual-e5-small-int8 (384dim).
- **Статус:** ✅ Fixed

## 2026-07-17 — Batch size (INC-BATCH)
- **Fix:** _BATCH_SIZE 64→4. Статус: ✅ Fixed

## 2026-07-17 — Хардкод 768-dim (INC-DIM)
- **Fix:** Авто-определение _lightweight_onnx_dim(). Статус: ✅ Fixed

## 2026-07-17 — InferRequest race (INC-RACE)
- **Fix:** Lock + single InferRequest. Статус: ✅ Fixed

## 2026-07-17 — Докстринг скорости (INC-DOCS)
- **Fix:** Комментарии обновлены. Статус: ✅ Fixed

## 2026-07-17 — install.py модель (INC-INSTALL)
- **Fix:** slug → multilingual-e5-small-int8. Статус: ✅ Fixed

---

## 2026-07-21 — God Objects продолжают расти (осознанный техдолг)

- **Источник:** Полный системный проход
- **Проблема:** 12 файлов >800 строк. layer.py (1197), engine.py (1083), graph_tools.py (>800), llama_runner.py (1515). Рост за неделю: -2 строк layer.py, +38 engine.py. Протокол §2.4 требует фиксации как осознанного техдолга.
- **Статус:** ⚠️ Осознанный техдолг. Декомпозиция не обязательна немедленно, но зафиксировано.
- **Дата пересмотра:** 2026-08-21 (через месяц)

## 2026-07-21 — TODO: llama_install.py SHA-256 хэши для macOS/Linux

- **Источник:** Полный системный проход
- **Проблема:**  — TODO про SHA-256 хэши для macOS/Linux, только Windows реализовано.
- **Статус:** ⚠️ Известно, не критично (Windows — основная платформа).

## 2026-07-21 23:30 — Полный системный проход: 8 замечаний, 4 из 6 закрыто на 100%

- **Источник:** AGENT_DIARY.md
- **Описание:** **Контекст:** Владелец провёл независимый полный аудит всех категорий риска за месяц.
565/565 passed на чистом clone+venv. Найдено 8 замечаний (3×P0, 3×P1, 2×P2).

**Что сделано (P0):**
1. **Version d...
- **Статус:** автоматически синхронизировано


---

## 2026-07-22 — wmic удалён в Win11 25H2 → RAM=0 (FIXED)

- **Что было:** `_get_process_ram()` вызывал `wmic process where processid=... get WorkingSetSize`. wmic.exe удалён в Windows 11 25H2 (KB5067470). На актуальной Windows все вызовы падали в except → возвращали 0. `intel_get_runtime_status` и `get_health_report` отдавали RAM=0 для всех процессов.
- **Статус:** ✅ Исправлено — замена на `ctypes.windll.psapi.GetProcessMemoryInfo` + `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`. Паттерн из `resource_monitor.py::_get_rss_windows()`.
- **Fix:** `src/core/intelligence/layer.py` — метод `_get_process_ram` переписан (~50 строк ctypes).
- **Тесты:** 519 passed, `_get_process_ram(os.getpid()) = 47 MB` (было 0).

---

## 2026-07-22 — asyncio.Event между loop'ами в ProjectIndexerRegistry (FIXED)

- **Что было:** `_ready_events` хранил `asyncio.Event`, привязанный к loop. `set_state()` вызывается из фоновых потоков без running loop → RuntimeError или зависание waiter.
- **Статус:** ✅ Исправлено — замена на `threading.Event` + `asyncio.to_thread(ev.wait, timeout)`.
- **Fix:** `src/core/indexing/project_indexer_registry.py` — 3 правки.
- **Тесты:** 519 passed, кросс-поточный тест PASS.

---

## 2026-07-22 — Embedding cache thrash: clear() вместо LRU (FIXED)

- **Что было:** `_embedding_cache` (Dict, max=1000) при переполнении вызывал `clear()` — сброс 1000 векторов → повторный embed → пики латентности каждые ~1000 уникальных запросов.
- **Статус:** ✅ Исправлено — `OrderedDict` + `popitem(last=False)` (LRU eviction). Кэш реранкера аналогично.
- **Fix:** `src/core/search/engine.py` — import OrderedDict, init, 2 cache-блока.
- **Тесты:** 519 passed, LRU-тест PASS.

---

## 2026-07-22 — hash() недетерминирован для ключей кэша (FIXED)

- **Что было:** `_embedding_cache` и `_reranker_cache` использовали `hash()` — недетерминирован между процессами (PYTHONHASHSEED). Кэш-промахи после рестарта, теоретические коллизии.
- **Статус:** ✅ Исправлено — `hashlib.blake2b(digest_size=8)` через `_cache_key()`. Детерминировано, быстрее md5.
- **Fix:** `src/core/search/engine.py` — функция `_cache_key`, 2 замены ключей, тип ключа int→str.
- **Тесты:** 519 passed, кросс-процесс детерминизм PASS.

---

## 2026-07-22 — sync→async bridge: per-call ThreadPoolExecutor (FIXED)

- **Что было:** `hybrid_search` и `_apply_multi_reranker` каждый раз создавали `ThreadPoolExecutor(max_workers=1)` + `asyncio.run()` — расточительно, O(N) потоков при массовых вызовах.
- **Статус:** ✅ Исправлено — module-level `_sync_executor = ThreadPoolExecutor(max_workers=2)`, оба bridge используют его.
- **Fix:** `src/core/search/engine.py` — import + executor + 2 замены.
- **Тесты:** 519 passed.

---

## 2026-07-22 — except (ImportError, Exception) маскирует баги (FIXED)

- **Что было:** `_get_process_cpu` использовал `except (ImportError, Exception)` — эквивалент `except Exception`, ImportError никогда не ловился отдельно.
- **Статус:** ✅ Исправлено — два отдельных `except ImportError` + `except Exception` с noqa: BLE001.
- **Fix:** `src/core/intelligence/layer.py` — 1 метод, `ruff.toml` — per-file-ignore.
- **Тесты:** 519 passed.
- **Техдолг:** 532 других broad excepts в codebase — постепенная очистка (P2).

## 2026-07-22 — P2-12: MODE_HYBRID dead code в composition_adapter.py (CLOSED)

- **Что было:** `composition_adapter.py` поддерживал `MODE_HYBRID` (L55-91) с полями `_definitions`, `_references`, `_file_to_symbols`. DI-контейнер всегда создавал `MODE_PURE` — hybrid-ветка никогда не выполнялась.
- **Статус:** ✅ Закрыто — файл удалён целиком (Задача 2/5 чистки мёртвого кода, 2026-08-02): 0 импортов в src/tests; MODE_PURE покрыт тестами (test_assignments.py, test_ast_cache_invalidation.py, полный pytest 674 passed).

---

## 2026-07-22 — P2-16: 532 broad except Exception в codebase (OPEN)

- **Что было:** Массовые `except Exception` в `layer.py` (~20), `engine.py` (~5), `db_manager.py`, `lsp_client.py` и др. маскируют программные ошибки под "graceful degradation". Одно конкретное `(ImportError, Exception)` уже исправлено (см. выше), но 532 других remain.
- **Статус:** ⏳ Отложено — массовый fix рискует регрессией. Требует per-file scoping: для каждой функции определить, какие исключения реальны, а какие — баги.
- **Guard:** после каждого сужения except — полный прогон тестов. Включить `BLE001` (blind-except) в ruff.toml.
- **Deadline:** постепенно, в течение 3 minor releases.

---

## 2026-07-22 — Audit 27 Issues: 12 fixed, 4 refuted, 10 deferred (PARTIAL)

### Fixed (this session)
| ID | Issue | File | Fix |
|----|-------|------|-----|
| 3 | `avg_results` formula `-` instead of `+` | error_handler.py:229 | Changed to `+` |
| 4 | `run_until_complete` in running loop | error_handler.py:592 | `_SYNC_POOL.submit()` |
| 5 | MD5 vs SHA256 hash mismatch | indexer.py:440 | `hashlib.sha256` |
| 7 | `split(";")` Windows-only | server.py:244 | `split(os.pathsep)` |
| 10 | Contradiction Ledger duplicate | main.py:222 | Removed duplicate |
| 11 | Dead code `_trigger_auto_index_if_empty` | server_factory.py:326 | Removed 70 lines |
| 13 | Unassigned expression | error_handler.py:318 | Added assignment |
| 14 | Memory leak `_cleanup_old_progress` | server.py | Periodic cleanup |
| 15 | `gc.collect()` every file | indexer.py:492 | Every 50 files |
| 25 | `log_crash` ignores param | main.py:114 | `traceback.print_exception` |
| 26 | Unused import overwritten | server.py:44 | Removed unused imports |

### Refuted
| ID | Claim | Reality |
|----|-------|---------|
| 1 | Factory not called | `factories[key](self)` correct at L138 |
| 2 | `error""` NameError | `err or ""` correct at L361 |
| 8 | asyncio.Lock before loop | Python ≥3.10 lazy binding OK |
| 12 | `_format_success_response` mutates | `_sanitize()` deep copies |

### Deferred (tech debt)
- **Issue 9:** `_cache` dict without Lock — low risk in sequential MCP
- **Issue 17:** sync→async `asyncio.run()` in thread — module-level executor exists
- **Issue 21:** Double tool instantiation (38 classes, minor perf)
- **Issue 24:** Redundant `pass` after `logger.warning` (1 instance)
- **Issue 27:** SQL without LIMIT (works correctly)

---

## 2026-07-22 — Wave 1+2: SQL injection, cache lock, recreate_table sync (FIXED)

### #22 SQL-инъекция в LanceDB (FIXED)
- **Что было:** LanceDB (DataFusion SQL) не поддерживает параметризованные запросы. Значения `parent_id`, `file_path`, `file_hash` подставлялись в `.where()` без экранирования.
- **Статус:** ✅ Исправлено — `_escape_sql_value()` во всех 7 точках.
- **Fix:** `src/core/indexing/indexer_table.py` — новый staticmethod; `indexer.py`, `engine.py`, `index_pipeline.py`, `file_move_manager.py` — все `.where()` вызовы экранированы.

### #9 Race condition в _cache dict (FIXED)
- **Что было:** `self._cache` (Dict) без Lock — при конкурентных MCP-запросах возможен `RuntimeError: dictionary changed size during iteration`.
- **Статус:** ✅ Исправлено — `threading.Lock` добавлен, все доступы под lock.

### #6 _safe_recreate_table без sync ссылок (FIXED)
- **Что было:** После пересоздания таблицы ссылки в `_status_reporter`, `_freshness_checker`, `_file_move_manager`, `_project_runner` оставались stale.
- **Статус:** ✅ Исправлено — вызов `_sync_table_ref()` через `hasattr` проверку.

---

## 2026-07-24 — Sandbox ALLOWED_MODULES inconsistency (TECH DEBT)

### #28 ALLOWED_MODULES broader than _USER_ALLOWED
- **Что было:** `ALLOWED_MODULES` (AST layer) содержит `multiprocessing`, `threading`, `http`, `socket`, `importlib`, `pickle`, `concurrent.futures`. `_USER_ALLOWED` (Layer 2 runtime) их НЕ содержит → Layer 2 блокирует на уровне import. Но ALLOWED_MODULES создаёт ложное ощущение безопасности.
- **Статус:** ⏳ Deferred — активной дыры нет (Layer 2 закрывает), но диссонанс между слоями нужно устранить.
- **Fix plan:** Синхронизировать ALLOWED_MODULES с _USER_ALLOWED или создать `ALLOWED_MODULES_STRICT` для subprocess. Deadline: следующий security audit.
- **Guard:** Аудит-лог (sandbox_audit.jsonl) показывает 106 violations / 352 executes — Layer 2 работает.

### #29 pickle в ALLOWED_MODULES
- **Что было:** `pickle` в ALLOWED_MODULES (AST проходит), но не в _USER_ALLOWED (Layer 2 блокирует `import pickle` в subprocess). `pickle.loads()` может выполнить произвольный код через `__reduce__`.
- **Статус:** ✅ Mitigated — Layer 2 блокирует. Но pickle лучше удалить из ALLOWED_MODULES явно.
- **Guard:** Проверено live: `import pickle; pickle.loads(b"x")` → status=error (Layer 2 catches).

## 2026-07-22 21:10 — Audit fixes P2-P3: tool count reconciliation (commit 5a522ead)

- **Источник:** AGENT_DIARY.md
- **Описание:** ### What was done
Second batch of audit fixes from the 20-item comprehensive audit:

| ID | Fix | File | Commit |
|----|-----|------|--------|
| P2-14 | LSP _handle_crash: terminate() before null (zom...
- **Статус:** автоматически синхронизировано


## 2026-07-22 21:45 — P0-2 FIX: wmic → ctypes GetProcessMemoryInfo

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. **`_get_process_ram(pid)`** в `src/core/intelligence/layer.py` — заменён вызов `wmic` (удалён в Win11 25H2 KB5067470) на `ctypes.windll.psapi.GetProcessMemoryInfo` с fallback на `k...
- **Статус:** автоматически синхронизировано


## 2026-07-22 22:15 — P1-3 FIX: asyncio.Event → threading.Event в ProjectIndexerRegistry

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. `asyncio.Event` в `_ready_events` заменён на `threading.Event` в `project_indexer_registry.py`.
2. `set_state()` — `ev.set()` теперь безопасен из любого потока (threading.Event.set...
- **Статус:** автоматически синхронизировано


## 2026-07-22 22:30 — P1-6 FIX: Embedding cache Dict → OrderedDict LRU

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. `self._embedding_cache` и `self._reranker_cache` заменены с `Dict` на `OrderedDict` в `engine.py`.
2. Cache HIT: добавлен `move_to_end(query_hash)` для LRU-порядка.
3. Cache overfl...
- **Статус:** автоматически синхронизировано


## 2026-07-22 22:35 — P1-5: intel_code_topology — УЖЕ ИСПРАВЛЕНО

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:** Верификация показала что все 4 правки P1-5 уже применены (видно в `git diff`):
1. `"definitions": []` добавлен в result (L185)
2. Definitions добавляются в `result["definitions"]`, а ...
- **Статус:** автоматически синхронизировано


## 2026-07-22 22:45 — P1-8 FIX: hash() → blake2b детерминированные ключи кэша

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. Добавлена функция `_cache_key(*parts: str) -> str` — `hashlib.blake2b(digest_size=8)` для детерминированных ключей.
2. `hash(variant)` для `_embedding_cache` заменён на `_cache_key...
- **Статус:** автоматически синхронизировано


## 2026-07-22 22:55 — P1-7 FIX: sync→async bridge — shared executor

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. Добавлен module-level `_sync_executor = ThreadPoolExecutor(max_workers=2)` в `engine.py`.
2. Оба sync→async bridge (`hybrid_search` и `_apply_multi_reranker`) теперь используют раз...
- **Статус:** автоматически синхронизировано


## 2026-07-22 23:10 — P1-4 FIX: except (ImportError, Exception) → разделение + ruff

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. `except (ImportError, Exception)` в `_get_process_cpu` заменён на два отдельных `except ImportError` и `except Exception` с `# noqa: BLE001`.
2. Добавлен `per-file-ignore` для `lay...
- **Статус:** автоматически синхронизировано


## 2026-07-22 23:30 — Audit 27 Issues: 12 confirmed & fixed, 4 refuted, 10 deferred

- **Источник:** AGENT_DIARY.md
- **Описание:** ### Context
Second audit found 27 issues across 10 files. Full verification against actual code confirmed 12 real bugs, refuted 4 false positives, and deferred 10 low-priority items.

### Verification...
- **Статус:** автоматически синхронизировано


## 2026-07-22 23:30 — PageRank v5: full scientific study, corrected blog post

- **Источник:** AGENT_DIARY.md
- **Описание:** **Verified from clean state:** yes (git clone + venv + install + pytest passed — all 598 tests pass)


**What was done:**
1. **v2**: Sparse vs dense graph comparison — 197 vs 301 edges, PageRank works...
- **Статус:** автоматически синхронизировано


## 2026-07-23 20:45 — Security fix: Sandbox bypass + Modification Guard enabled

- **Источник:** AGENT_DIARY.md
- **Описание:** ### What was done
Three critical security fixes from architectural review:

| Issue | Fix | File | Lines |
|-------|-----|------|-------|
| **Sandbox bypass** — `obj.__getattribute__(obj, "__subclasse...
- **Статус:** автоматически синхронизировано


## 2026-07-23 21:00 — INC-XXXX: Sandbox denylist bypass via __getattribute__ attribute access

- **Источник:** AGENT_DIARY.md
- **Описание:** ### Symptom
`validate_code()` в `src/core/sandbox/executor.py` пропускает код, получающий доступ к `__subclasses__`/`__globals__`/`__bases__` через `obj.__getattribute__("__subclasses__")` вместо прям...
- **Статус:** автоматически синхронизировано


## 2026-07-23 21:10 — modification_guard: connected to WriteTool + fail-closed + ack bypass

- **Источник:** AGENT_DIARY.md
- **Описание:** ### What was done
Three fixes from the same review:

1. **Guard connected to WriteTool.execute()** (`src/mcp/tools/write_tools.py:70`)
   Previously: `ack_impact` used, but `@modification_guard` decor...
- **Статус:** автоматически синхронизировано


## 2026-07-25 00:10 — 6 bugs fixed: ONNX stderr, CodebaseTool self, Ledger NoneType+hang, ONNX model mismatch, subprocess deadlock

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** (a) print(file=sys.stderr) crashes in Zed env. (b) inspect.signature+locals() antipattern. (c) Ledger discrepancies is int not list. (d) ONNX model_name="bge-m3" mi...
- **Статус:** автоматически синхронизировано


## 2026-07-27 — Audit Round 4: P1/P2/P3 bugs from full subsystem audit

**Status:** 🔍 IN PROGRESS — P1 fixes in progress

**Source:** Full audit across 5 subsystems (graph.py, cypher stack, server_tools, intelligence/layer.py, write_tools.py, search/engine.py, error_handler.py, remote_embedder.py, indexer.py, db_manager.py)

### P1 — Critical (fix before next release)

| # | Subsystem | Bug | File:Line | Type |
|---|-----------|-----|-----------|------|
| 1 | search/engine.py | SQL injection via `layer` param (f-string) | engine.py:316, 661 | SQL injection |
| 2 | write_tools.py | `file_path` without FileGuard — path traversal | write_tools.py:82-83 | path traversal |
| 3 | write_tools.py | `new_name`/`symbol` not validated as identifier | write_tools.py:99-126 | code injection |
| 4 | write_tools.py | `_uri_to_path` without project_path check | write_tools.py:450-455 | path traversal |
| 5 | error_handler.py | `elapsed = ... - 1000` instead of `* 1000` | error_handler.py:454 | metric bug |
| 6 | error_handler.py | `future.cancel()` not called on timeout | error_handler.py:513-514 | thread leak |
| 7 | remote_embedder.py | silent zero-vector fallback masks provider failure | remote_embedder.py:717-718 | silent data corruption |
| 8 | db_manager.py | `search()` without `_write_lock` vs `reset_connection()` | db_manager.py:304-307 | race → crash |
| 9 | graph.py | `shortest_path` path explosion (BFS stores all paths) | graph.py:636-683 | OOM |
| 10 | indexer.py | `move_chunks_metadata` delete+add not atomic | indexer.py:494-502 | data loss on crash |
| 11 | cypher_executor.py | `_get_conn()` without lock | cypher_executor.py:51-52 | DB lock error |
| 12 | test_searcher.py | ~~stub with `assert True`~~ → G-1 закрыт 2026-07-31: 5 stub-тестов заменены на 52 настоящих (658 passed) | tests/test_searcher.py | ~~QA bypass~~ ✅ FIXED |

### P2 — Important (fix within sprint)

| # | Subsystem | Bug | File:Line | Type |
|---|-----------|-----|-----------|------|
| 13 | layer.py | 22 broad `except Exception` masks errors | layer.py:multiple | error masking |
| 14 | layer.py | `hash(line) % 10000` nondeterministic IDs | layer.py:662 | id collision |
| 15 | layer.py | `netstat -ano` Windows-only in cross-platform code | layer.py:299-314 | platform bug |
| 16 | layer.py | asyncio.Lock + threading.Lock mixed for same data | layer.py:110-112 | race condition |
| 17 | engine.py | `_cache` without TTL — stale after reindex | engine.py:643-718 | stale data |
| 18 | engine.py | `asyncio.run` in ThreadPoolExecutor bottleneck | engine.py:273-284 | perf |
| 19 | write_tools.py | `_infer_package` rstrip(".py") removes wrong chars | write_tools.py:307-310 | bug |
| 20 | write_tools.py | non-atomic write without backup | write_tools.py:386-413 | data loss |
| 21 | remote_embedder.py | `mode_lock` only on read, not during HTTP request | remote_embedder.py:644-645 | race |
| 22 | error_handler.py | `_TIMELINE.pop(0)` O(n) under lock | error_handler.py:206-218 | perf |
| 23 | db_manager.py | PID lock race → crash instead of retry | db_manager.py:374-398 | crash |
| 24 | db_manager.py | `_write_lock = threading.Lock` not RLock | db_manager.py:48 | future deadlock |
| 25 | indexer_table.py | `_escape_sql_value` manual escaping (fragile) | indexer_table.py:26-47 | fragile defense |
| 26 | graph.py | `unlink()` without `finally` — temp file leak | graph.py:1017, 1083 | resource leak |
| 27 | graph.py | `batch_add_edges` N+1 queries | graph.py:917-962 | perf |
| 28 | ruff.toml | BLE001 not in select — 532 broad excepts | ruff.toml | lint gap |

### P3 — Low priority

| # | Subsystem | Bug | File:Line | Type |
|---|-----------|-----|-----------|------|
| 29 | cypher_sql.py | variable-length paths `[*1..3]` silently ignored | cypher_sql.py:209-217 | wrong result |
| 30 | cypher_executor.py | SQL + params leaked in MCP response | cypher_executor.py:69-70 | info leak |
| 31 | graph.py | `detect_dead_code` LIMIT 200 silent truncation | graph.py:725 | wrong result |
| 32 | error_handler.py | traceback in MCP response | error_handler.py:495 | info leak |
| 33 | layer.py | manual git object parsing (no packfile support) | layer.py:729-787 | incomplete |
| 34 | write_tools.py | `_apply_delete` by line_no without content check | write_tools.py:456-483 | wrong deletion |
| 35 | engine.py | 18 broad except returning [] | engine.py:multiple | error masking |

## 2026-08-01 — HTTP 400 фикс llama.cpp embedder (v3.3.10) + инцидент «индексация умерла с клиентом»

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (HTTP 400); индексация 🔄 повторно запущена detached
**Root Cause:** чанки длиннее 512 токенов → llama.cpp возвращал HTTP 400 (×4 в прогоне 23:28 31.07); фикс — усечение через HF to...
- **Статус:** автоматически синхронизировано


## 2026-07-31 — P0 deadlock реиндекса + z.ai review обработка (16 пунктов)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (P0 deadlock; z.ai: 3 CONFIRMED/1 partial/12 REFUTED)
**Root Cause:** регрессия ac6e5ba0e P1-3 (19:33) — `_parse_file_only` read-секция под `_table_write_lock` (RLock), а Phase 1 в...
- **Статус:** автоматически синхронизировано


## 2026-07-31 — G-1 закрыт: 5 stub-тестов (B11/P1-12) заменены на настоящие (52 теста)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** B11 (KNOWN_ISSUES.md:177-187) — verify_diary ссылался на несуществующие тесты; созданы stub'ы с `assert True` (test_file_exists, test_searcher, test_idle_reload, te...
- **Статус:** автоматически синхронизировано


## 2026-07-31 — Qwen review верификация: 12✅/4❌/2⏳ + P0-5 sandbox, P1-17 CodeParser race

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (P0-5, P1-17, P2-21..P2-27 закрыты; 4 REFUTED, 2 ACCEPTED)
**Root Cause:** sandbox — ALLOWED_MODULES шире runtime _USER_ALLOWED (importlib* — RCE-вектор при расхождении слоёв) + `o...
- **Статус:** автоматически синхронизировано


## 2026-07-31 — P0-3 закрыт: CI больше не клонирует сам себя (--no-clone)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** `scripts/verify_clean_state.sh` делал `git clone` hardcoded URL даже в CI, где раннер уже checkout-нул тот же SHA — тестировался внешний HEAD, а не проверяемый комм...
- **Статус:** автоматически синхронизировано


## 2026-07-31 — Остаток ISSUE.md закрыт: graph/db_manager/cypher/indexer/error_handler/layer + P0 git_hooks_installer

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (ISSUE.md P1-1..P1-14, P2-14..P2-17, P3-1..P3-14 — все закрыты)
**Root Cause:** остаточный долг аудита: BFS хранил полные пути (O(V×depth) память), batch_add_edges — N+1 запросов; ...
- **Статус:** автоматически синхронизировано


## 2026-07-31 — Flaky gate-zero: ENOSPC (C: 100%), не TOCTOU

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (root cause найдена)
**Root Cause:** C: диск заполнен на 100% (0 avail). `test_commit_memory.py` делает `git init`/`git commit` в pytest-temp (`C:\...\Temp\tmp...`) → `WinError 112...
- **Статус:** автоматически синхронизировано


## 2026-07-31 — P0/P1 fix batch: rate_limiter async-lock, lsp_client lifecycle, write_tools LSP sync, index_parser, modification_guard

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** Миграция на threading.Lock (INC-53EC / REFC-03) была неполной — 6 мест с `async with self._lock` в rate_limiter.py (AttributeError в рантайме); lsp_client не reaped...
- **Статус:** автоматически синхронизировано


## 2026-07-26 — Systematic Cross-Check Audit: Fix Phase

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (7 discrepancies resolved)

**Fixes applied:**
1. AGENTS.md:1 — "39 Registered Tools" → "48 Registered Tools" ✅
2. AGENTS.md:277 — "## 2. AVAILABLE TOOLS (37)" → "## 2. AVAILABLE T...
- **Статус:** автоматически синхронизировано


## 2026-07-27 — P0 fixes: alias SQL injection, layer SQL injection, CI Windows paths, sandbox docstring

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (4 P0 issues resolved)

**Fixes applied:**
1. cypher_sql.py L84 — alias validation via re.fullmatch before f-string substitution (P0-1)
2. engine.py L352-356, L740-742 — layer para...
- **Статус:** автоматически синхронизировано


## 2026-07-15 05:52 — Операция «Санация» завершена

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** Multiple P0/P1 issues found during comprehensive audit.
**Fix:** Fixed all critical issues including RCE sandbox, bare excepts, and dead code.
**Guard:** Pre-commit...
- **Статус:** автоматически синхронизировано


## 2026-07-12 23:30 — Docs Sync: полный аудит 15 doc-файлов в 3 языках под v3.2.0

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** Documentation was out of sync with runtime code across 15 files in 3 languages.
**Fix:** Full docs sync — all 15 files updated to match v3.2.0 runtime state.
**Guar...
- **Статус:** автоматически синхронизировано


## 2026-07-12 — Bugfix: token_type_ids ломал ONNX batch. RAM thresholds починены

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** token_type_ids was breaking ONNX batch processing, and RAM thresholds were incorrect.
**Fix:** Fixed token_type_ids handling and updated RAM thresholds.
**Guard:** ...
- **Статус:** автоматически синхронизировано


## 2026-07-11 22:30 — Zed Deep Dive: ACP Agent Registry (38 agents), basedpyright LSP, Zed internals

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** ACP Agent Registry had 38 agents but only 37 were registered in MCP tools.
**Fix:** Reconciled agent count with tool count.
**Guard:** Agent count now tracked in se...
- **Статус:** автоматически синхронизировано


## 2026-07-09 23:00 — BREAKTHROUGH: Qwen3-Embedding-0.6B ctx=1024 — Новый король

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** Previous embedding models had suboptimal performance.
**Fix:** Switched to Qwen3-Embedding-0.6B with ctx=1024.
**Guard:** Benchmark validates Qwen3 at EN=0.378, RU=...
- **Статус:** автоматически синхронизировано


## 2026-07-07 23:30 — Fix: P1+P2 — get_health_report timeout + branch_info async

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** get_health_report was timing out due to loading entire LanceDB table.
**Fix:** Optimized get_health_report to use indexed queries.
**Guard:** Timeout added to healt...
- **Статус:** автоматически синхронизировано


## 2026-07-27 — P0 fixes: alias SQL injection, layer SQL injection, CI Windows paths, sandbox docstring

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (4 P0 issues resolved)

**Root Cause:** Previous audit session identified 4 P0 bugs across cypher stack, search engine, CI, and codebase tool.

**Fix:**
1. cypher_sql.py L84 — adde...
- **Статус:** автоматически синхронизировано


## 2026-07-07 01:30 — Ultra-Lean reranker: одностадийный cross-encoder вместо трёхстадийного pipeline

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** Reranker pipeline was too complex and slow.
**Fix:** Simplified to single-stage cross-encoder reranker.
**Guard:** Benchmark validates bge-reranker-v2-m3 at 27 t/s....
- **Статус:** автоматически синхронизировано


## 2026-07-05 12:00 — Initial project setup

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** Initial project setup and configuration.
**Fix:** Set up project structure, MCP server, and basic tools.
**Guard:** Pre-commit hooks installed.
**verified_from_clea...
- **Статус:** автоматически синхронизировано


## 2026-07-27 — P1 fixes: error_handler elapsed bug, write_tools path traversal, remote_embedder silent fallback

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (3 P1 issues resolved)

**Root Cause:** Audit identified systemic bugs across error_handler, write_tools, and remote_embedder.

**Fix:**
1. error_handler.py L530 — fixed `elapsed =...
- **Статус:** автоматически синхронизировано

## 2026-08-03 — Задача 5/5: Граф в каждом режиме поиска (INC: CALLS в методы = 0)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, не запушено; синхронизировано в расширение)
**Root Cause:** (1) `_extract_calls_recursive` эмитил caller без класса → `add_edge` молча дропал рёбра в методы (0 CALLS в ...
- **Статус:** автоматически синхронизировано


## 2026-08-03 20:15 — Верификация Задачи 5/5 после полного реиндекса + дедуп callers

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (полный reindex, 4746 чанков): nodes 6566, edges 18720; find_references('search_with_mode') 0→1; дедуп callers в graph_adapter_pure.find_references (рендер `🔗 Вызывается из:` без дублей); pytest 725 passed / 13 skipped.
- **Статус:** автоматически синхронизировано


## 2026-08-03 02:10 — Задача 4/5: Артефакты вынесены из проекта в системную папку

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, не запушено; синхронизировано в расширение)
**Root Cause:** MCP писал индексы/граф/память/телеметрию ВНУТРЬ пользовательского проекта (.codebase_indices/, .codebase/gra...
- **Статус:** автоматически синхронизировано


## 2026-08-03 01:10 — Задача 3/5: Startup Diagnostics + P0-фикс INC-6471 (GetExitCodeProcess)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, локально не запушено; синхронизировано в расширение)
**Root Cause:** (1) При старте/сбое пользователь видел Rust-трейс (`lance-io-8.0.0\src\local.rs`) вместо человеческ...
- **Статус:** автоматически синхронизировано


## 2026-08-03 00:20 — Задача 2/5: DatabaseGateway — PID-lock вынесен в DatabaseLock (модуль + тесты)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (локально, не запушено)
**Root Cause:** PID-lock (Layer 3 defense) был приватным 140-строчным методом LanceDBManager (_acquire_pid_lock) — не тестируем, не переиспользуем; wait_tim...
- **Статус:** автоматически синхронизировано


## 2026-08-02 23:55 — Задача 2/5: чистка мёртвого кода DI + файлы-адаптеры

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (локально, не запушено)
**Root Cause:** 5 DI-регистраций (DbPathKey, FileGuard-singleton, SymbolIndex, ResourceMonitorKey, ResourceMonitor-в-DI) никогда не резолвились; composition...
- **Статус:** автоматически синхронизировано


## 2026-08-02 23:30 — Исследование перед Задачей 2/5 (DatabaseGateway): 4 вопроса владельца закрыты фактами

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Исследование завершено (read-only; правок кода нет)
**Root Cause (вопроса):** владелец описал архитектуру Gateway по памяти — требовалась проверка «что переписывать, что не сломать» до к...
- **Статус:** автоматически синхронизировано


## 2026-08-02 23:10 — INC-6E12: FileGuard в write_tools — fail-open → fail-closed (задача 1/5 «идеального кода»)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (локально, не запушено; runtime — живой MCP работает с синхронизированным файлом)
**Root Cause:** `_validate_file_in_project` (write_tools.py:93) возвращал None при недоступности i...
- **Статус:** автоматически синхронизировано


## 2026-08-02 22:50 — INC-6C62 «вечная ошибка» реиндекса: физическое пересоздание таблицы LanceDB

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, локально не запушено; runtime-проверка требует Reload Window)
**Root Cause:** drop_table+create_table в LanceDB НЕ удаляет физические файлы, залоченные mmap живого проц...
- **Статус:** автоматически синхронизировано


## 2026-08-02 00:26 — Реиндекс падает: lance 'Not found' (3 подряд) + 2 MCP-процесса + stale table refs

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🔴 Open — требуется действие владельца
**Root Cause:** (1) 2 MCP-процесса на одной БД с 23:47:00 (PID 4576 активный + PID 21616 зомби, 156ms CPU, завис при старте) — rmtree/drop блокируются...
- **Статус:** автоматически синхронизировано


## 2026-08-01 23:55 — Contradiction Ledger: флапающий check_commit_exists + push v3.3.11 + верификация чанков

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** verify_diary.py check_commit_exists — git cat-file с timeout=5s; при старте MCP (auto-index, embedder, reranker 499MB, Defender scan) git не укладывался в 5s → Time...
- **Статус:** автоматически синхронизировано


## 2026-08-03 22:45 — P1: hub codebase — каналы write/index падали ImportError'ом (исправлено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, не запушено; ext синхронизирован cp)
**Root Cause:** codebase_tool.py импортировал несуществующие модули `symbol_write_tools.SymbolWriteTool` и `index_tools.IndexTool` → `codebase(action="write"|"index")` отвечали «No module named…». rename_symbol/replace_symbol падали с 20:52 (телеметрия).
**Fix:** `_action_write` → write_tools.WriteTool (убран kwarg project_root); `_action_index` — диспетчер по path: status|progress|timeline|health|project_dir|notify.
**Guard:** 37 passed (test_write_tools) + 10 passed (health/architecture/index_guard); live-проверка после Reload Window.
- **Статус:** ✅ Fixed, live-подтверждено на RUN_ID e3f3aabd7186 (2026-08-03): codebase(action="index", path="status") → 4842 chunks; codebase(action="write", ...) → modification guard + impact_token. E2E-цепочка edit→notify_change→reindex (4842→4857)→search_code нашёл новый контент.


## 2026-08-01 22:50 — HTTP 400 llama.cpp embedder: v1 (HF truncation) ОПРОВЕРГНУТ → v2 (native /tokenize) + полный реиндекс 4677 чанков

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (v3.3.11, локально, не запушено)
**Root Cause:** GGUF multilingual-e5-small: n_ctx_train=512 → llama.cpp капит слот до 512. HF-токенизатор ≠ GGUF-токенизатор (разные BPE): после ус...
- **Статус:** автоматически синхронизировано

## 2026-08-03 20:40 — search_code рендерил «📄 — (line , —)»: корень в db-level manifest, а не в рендере

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, не запушено; синхронизировано в расширение)
**Symptom:** `search_code(mode=fast)` возвращал `1 results` с пустым рендером `📄 **—** (line , —)` вместо файла/строки/кода....
- **Статус:** автоматически синхронизировано


## 2026-08-03 23:40 — Contradiction Ledger: 3 ложных срабатывания в verify_diary.py (исправлено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код, не запушено; ext синхронизирован cp)
**Symptom:** при каждом старте MCP логи предупреждали «Contradiction Ledger: 3 расхождения»: ❌ Функция `sustained`, ❌ Тест `test_race_exactly_one_winner`, ⚠️ Коммит `75428c27c2ae`.
**Root Cause (3 бага в scripts/verify_diary.py):** (1) regex `name\s*\(` в `_extract_code_functions` ловил прозу «sustained (2026-07-26)» в backtick-контенте как вызов функции; (2) hex-сканер коммитов не исключал токен «RUN_ID <hex>» (RUN_ID — runtime-идентификатор, не git-коммит; в _COMMIT_EXCLUDE были только 2 хардкод-значения — пластырь); (3) `_check_test_file_exists` искал ФАЙЛ `tests/test_<имя>.py` и не находил тест-МЕТОД внутри класса (test_database_lock.py::TestContention) — SymbolCache (сканирует все .py, ловит отступные def) не использовался. Плюс заголовок `## CONTRADICTION [date]` не парсился как отдельная запись — символы §4.9-записи атрибутировались предыдущей.
**Fix:** строгий `name\(` (без пробела перед скобкой); удаление токена «RUN_ID <hex>» до hex-сканирования; fallback is_test → SymbolCache.has_function; regex заголовка принимает `(?:CONTRADICTION\s+)?`. Дневник: +2 маркера `verified_from_clean_state` (записи 21:50 и 22:45 — обе live-подтверждены).
**Guard:** `python scripts/verify_diary.py --skip-gate-zero` → 21 ✅ / 0 ❌ (было 18/3); тесты на verify_diary отсутствуют — урок в EXPERIMENTS_LOG#exp-16.
- **Статус:** ✅ Fixed, live-проверено (21/0) — нужен Reload Window, чтобы фоновый поток старта подхватил фикс

## 2026-08-03 23:15 — P1 REOPEN: hub codebase write — dispatch терял sub-action (guard маскировал баг)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код + 15 новых тестов, ext синхронизирован; live-проверка после Reload Window)
**Root Cause:** фикс 22:45 перевёл `_action_write` на WriteTool, но передавал `action="write"` (под-...
- **Статус:** автоматически синхронизировано


## 2026-08-03 23:20 — ONNX embedder: 2× off-by-one пути — тихий fallback на llama.cpp (5+ падений/день)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код, ext синхронизирован; live через продакшн-путь get_onnx_client)
**Root Cause:** (1) `onnx_client.py` PROJECT_ROOT = parent×3 из src/core/embedder/ → `…/src` (не корень) → «Ser...
- **Статус:** автоматически синхронизировано


## 2026-08-03 23:45 — E2E-проверка MCP-цепочки + Contradiction Ledger 21/21 + Py3.14 audit

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (live RUN_ID e3f3aabd7186) + ✅ Fixed (verify_diary 3 бага, error_handler 1 латентный)
**Root Cause (2 независимых):** (1) verify_diary.py — 3 ложных ❌ при каждом старте: regex л...
- **Статус:** автоматически синхронизировано


## 2026-08-03 22:30 — Слияние DEV_DIARY.md → AGENT_DIARY.md завершено (§4.7)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Closed
**Root Cause:** исторически два параллельных дневника; заголовок «ARCHIVED» в DEV_DIARY (от 07-19) не соответствовал факту — 27 из 28 записей (07-17..07-19) так и не были перенесе...
- **Статус:** автоматически синхронизировано


## 2026-08-03 21:55 — search_code quality/deep/auto зависали на 30с: sync-поиск блокировал main loop и отравлял _sync_executor

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, синхронизировано в расширение; live-проверка после Reload Window)
**Root Cause:** search_code (async) вызывал sync `search_with_mode` прямо в main loop → `hybrid_search...
- **Статус:** автоматически синхронизировано


## 2026-08-03 21:50 — Ложное «Обнаружен второй экземпляр MCP» на собственном lock-е (startup_diagnostics)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, синхронизировано в расширение; live-подтверждено на новом инстансе 21:32)
**Root Cause:** inspect_pid_lock не знал собственный PID: lock, который живой MCP держит всю с...
- **Статус:** автоматически синхронизировано


## 2026-08-03 22:45 — Ротация дневника §4.8 (июль → docs/archive/AGENT_DIARY_2026_07.md)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done
**Root Cause:** дневник 861 строка (> лимит 300) — перегрузка контекста.
**Fix:** все записи < 2026-08-01 перенесены в docs/archive/AGENT_DIARY_2026_07.md (заголовок ARCHIVE — см. A...
- **Статус:** автоматически синхронизировано


## 2026-08-03 23:55 — §1.19 Hard Triggers внедрены в личный AGENTS.md (RESOLVED)

**Symptom:** протокол (§1.15, §1.16, §1.18, §3.5, §0.1.1) сформулирован как «обязан» — агент выполняет шаги, но не думает по ним (нет Phase Zero, Red Team, обобщения, немедленной meta-check, Verification Ledger).
**Root Cause:** «Обязан» — карта, которую можно не читать. Нужны «рельсы» («запрещено без»).
**Fix:** §1.19 ЖЁСТКИЕ ТРИГГЕРЫ: 5 блокираторов (Phase Zero, Red Team, grep-обобщение, немедленный META-CHECK, Verification Ledger ≥3 подзадачи). Формат «запрещено без» + Red Team формат `[🔓 RED TEAM] Атака N → Защита/Нет защиты`.
**Status:** ✅ внедрено в C:\Users\misha\AppData\Roaming\Zed\AGENTS.md (1375→1423 строки). Red Team 5/5 защищено на самой правке.

## 2026-08-03 23:55 — Аудит audit.md: 29 вердикты размечены (PARTIAL — 7 неисправлено, 15 рекомендаций)

**Symptom:** audit.md (2053 строк) содержал 24 пункта + solo-dev 5 без статусов.
**Root Cause:** аудит накапливался без обновления статусов.
**Fix:** скрипт .local/patch_audit_status.py вписал 29 вердиктов с File:Line: 4✅ (DI, resolve root, RRF, ack_impact), 3⚠️ (asyncio.Lock, progress cleanup, _distance inconsistency), 7❌ (Heartbeat GetLastError, SearchResultReranker weights, BM25 sync reindex, SQLite schema cols, PYTHONUTF8, shell=True, CodeParser leak), 15📝 рекомендаций (cancellation, OTel, Prometheus, ConfigReloader, chaos, property-based, AgentFriendlyError, ResourceGuard, uninstall, DevModeReloader и др.).
**Status:** ⚠️ частично — баги 1,2,3,6,8,10,11,12,13,16,17 остаются открытыми; рекомендации 15-29 — новые фичи, не баги.

## 2026-08-03 23:55 — Документация синхронизирована (RESOLVED)

**Symptom:** README/docs badges 649/667 tests (реально 747), tool counts 42/48 (реально 48), dates 2026-07-21, CHANGELOG пуст в корне.
**Fix:** README.md + docs/{ru,zh}/README.md: badges 747 passed, 48 tools, dates 2026-08-03; ru/zh heading anchors fixed; docs/en/CHANGELOG.md уже актуален (3.3.11, 48 tools).
**Status:** ✅ docs/en/ru/zh/README.md + bump_version --check ✅ (3.3.11).

## 2026-08-03 23:55 — Commit+push выполнен (RESOLVED)


## 2026-08-03 — Аудит audit.md: открытые пункты (29 вердиктов, 6✅, 6❌, 6⚠️, 11📝)

### ✅ ИСПРАВЛЕНО (спринт 2026-08-04: 5/6 FIXED + 1 REFUTED + Item 10)

| # | Пункт | Файл | Статус | Доказательство |
|---|-------|------|--------|----------------|
| 2 | HeartbeatService: нет SetLastError(0) перед OpenProcess, fail-open | src/mcp/server_factory.py:57-68 | ✅ Fixed | SetLastError(0) перед OpenProcess; GetLastError читается только при handle==0; fail-open сохранён. Red Team 5/5. |
| 6 | SearchResultReranker: hardcoded веса bm25_weight=0.3, dense_weight=0.7 | src/config/settings.py + src/core/search/engine.py:86-89 | ✅ Fixed | SearchConfig.bm25_weight/dense_weight из env (BM25_WEIGHT/DENSE_WEIGHT, дефолты 0.3/0.7); engine читает get_config().search.* |
| 8 | BM25 reindex callback: синхронный reindex в DebounceBatch | src/core/di_container.py:296-300 | ❌ Refuted | `BM25Mixin.reindex()` (src/core/search/bm25.py:37-40) = только `_bm25 = None` под `_bm25_lock` (O(1), инвалидация кэша). Полный rebuild — лениво при следующем поиске. Блокировки потока НЕТ. Предыдущая запись ledger «FIXED via ThreadPoolExecutor» — ложь, правки не было. |
| 10 | LanceDB _distance: комментарий «чем больше, тем ближе» неверен → инверсия fast-mode сортировки | src/core/search/engine.py:166-169, 791 | ✅ Fixed | Эксперимент lancedb 0.34.0 (IVF_FLAT cosine): _distance = 1−cos_sim, МЕНЬШЕ = БЛИЖЕ, ASC (сам вектор=0.0). sort(reverse=True) убран → sort() по возрастанию; комментарий исправлен; тест test_search_with_mode_fast_sorts_distance_ascending (757 passed, 0 failed). |
| 11 | SQLite schema validation: только таблицы, нет колонок | src/mcp/server.py:266-289 | ✅ Fixed | PRAGMA table_info(scoped_kv_store) → {key, value}; PRAGMA table_info(workspaces) → {workspace, data} |
| 12 | Encoding: нет PYTHONUTF8=1 | src/utils/zed_config.py:270-273 | ✅ Fixed | env[\"PYTHONUTF8\"] = \"1\" в _make_server_entry (Windows cp1251 → UTF-8) |
| 13 | install.py: shell=True в subprocess | install.py:254-264, 549-556 | ✅ Fixed | _run() → shlex.split + shell=False; step_pip Popen → список аргументов + shell=False; фикс stray `)` (синтаксическая ошибка) |
| 10 | LanceDB _distance: комментарий «чем больше, тем ближе» неверен → инверсия fast-mode сортировки | src/core/search/engine.py:166-169, 791 | ✅ Fixed | Эксперимент lancedb 0.34.0 (IVF_FLAT cosine): `_distance = 1 − cos_sim` ∈ [0,2], ASC, меньше = ближе (сам вектор 0.0, ортогональный 1.0). sort(reverse=True) убран, комментарий исправлен. Тест test_search_with_mode_fast_sorts_distance_ascending (падает на старом коде). 757 passed, 4 skipped, 0 failed. |

### ⚠️ ЧАСТИЧНО (P2 — требуют доработки)

| # | Пункт | Файл | Статус |
|---|-------|------|--------|
| 3 | asyncio.Lock создаётся вне event loop (cross-loop risk) | src/core/search/engine.py:91 | 🟡 Partial |
| 4 | Progress tracking: эвристический cleanup (len > 10, 1ч) | src/mcp/server.py:202-229 | 🟡 Partial |
| 17 | PropertyGraph: lock есть, _recover_from_wal отсутствует | src/core/graph.py:742-795 | 🟡 Partial |
| 19 | Rate limiting: только provider-level, нет MCP-level | src/core/rate_limiter.py | 🟡 Partial |
| 26 | Agent-friendly errors: error_boundary есть, AgentFriendlyError нет | src/mcp/tools/write_tools.py:135 | 🟡 Partial |

### 📝 РЕКОМЕНДАЦИИ (P3/P4 — tech debt / новые фичи)

| # | Пункт | Файл | Статус |
|---|-------|------|--------|
| 15 | Cancellation handling: MCP запросы не отменяются | — | 📝 Tech Debt |
| 16 | Tree-sitter: CodeParser leak (нет close/__del__) | src/core/indexing/parser.py:21 | 📝 Tech Debt |
| 18 | MCP Progress notifications: не используются notifications/progress | — | 📝 Tech Debt |
| 20 | OpenTelemetry: нет distributed tracing | — | 📝 Tech Debt |
| 21 | Prometheus: нет metrics integration | — | 📝 Tech Debt |
| 22 | Config hot-reload: ConfigReloader отсутствует | — | 📝 Tech Debt |
| 23 | Chaos-тесты: kill process during indexing | — | 📝 Tech Debt |
| 24 | Property-based тесты для scoring (RRF, cosine) | — | 📝 Tech Debt |
| 27 | ResourceGuard: защита от OOM | — | 📝 Tech Debt |
| 28 | One-command uninstall в install.py | install.py | 📝 Tech Debt |
| 29 | Hot-reload кода: DevModeReloader отсутствует | — | 📝 Tech Debt |


**Symptom:** 19+ изменённых файлов, unpushed commit 5ce0eaa3 (origin/main = ab44b00d).
**Fix:** commit 8a07c23e (34 files, +2362/-522), pre-commit OK (verify_diary 25✅, stale_detector OK), push origin/main.
**Status:** ✅ origin/main up to date (HEAD = 8a07c23e).

## 2026-08-04 22:30 — Приведение в порядок корня проекта (root cleanup)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (закоммичено в этой сессии)
**Root Cause:** в корне накопились одноразовые pytest-обёртки с hardcoded путями (runner.py, quickrun.py, do_test.py, execute_test.py, quick_test.py, _ru...
- **Статус:** автоматически синхронизировано


## 2026-08-04 21:00 — ZED CRASH-LOOP: 7 рестартов за 2 часа — всплески памяти агента 7.5-8.6GB + дефицит системных ресурсов

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Root Cause подтверждён (лог+счётчики+EventLog+GitHub); фикс — действия владельца, код не менялся
**GitHub-подтверждение (2026-08-04 21:15):** `GitHub#60793` — точная копия кейса (Win11 +...
- **Статус:** автоматически синхронизировано


## 2026-08-04 — fast-mode сортировка инвертировала топ-результаты (cosine _distance ASC)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код + 1 регрессионный тест)
**Root Cause:** комментарий `engine.py:166` утверждал «негативная косинусная дистанция (чем больше, тем ближе)» — проверено экспериментом (lancedb 0.34...
- **Статус:** автоматически синхронизировано


## 2026-08-03 23:55 — Сессия: §1.19 Hard Triggers + аудит 29 пунктов + docs sync + commit/push

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done
**Root Cause:** протокол требовал жёстких триггеров (§1.19), аудит audit.md был неразмечен, README/doc badges устарели (649→747), DEV_DIARY не архивирован, CHANGELOG пуст, unpushed ...
- **Статус:** автоматически синхронизировано


## 2026-08-04 — Спринт: 6 пунктов аудита (5 ✅ Fixed, 1 ❌ Refuted) + docs + commit/push

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (5/6 FIXED, 1/6 REFUTED)
**Root Cause:** 6 ❌ P1/P2 пунктов из experiments/audit.md требовали фикса: Heartbeat GetLastError, hardcoded reranker weights, BM25 sync reindex, SQLite sch...
- **Статус:** автоматически синхронизировано

## 2026-08-05 21:56 — Открытая нить закрыта: progress_state удалён (dead code), project_context → job_manager (единый источник прогресса)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** `_create_progress_callback`/`_last_progress` (src/core/progress_state.py) в проде не вызывались (внутренний callback layer.py маппит прогресс в `job.progress`, не в...
- **Статус:** автоматически синхронизировано


## 2026-08-05 22:50 — Следующий шаг: get_last_progress → core, фикс bump_version, фикс sys.path-загрязнения теста (FIXED, будет закоммичено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (не закоммичено — коммит следом)
**Root Cause:** (1) техдолг из ARCH-03-цепочки: `project_context` импортировал `get_last_progress` из mcp.server — направление core→mcp оставалось;...
- **Статус:** автоматически синхронизировано


## 2026-08-05 22:10 — experiments/audit.md: 16 пунктов верифицировано, 12 исправлено (FIXED, не запушено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (не закоммичено — по команде владельца)
**Root Cause:** audit.md накопил 4 наложенных аудита; свежий (ARCH/BL/WIN/ZED/SEC/TEST) содержал подтверждаемые проблемы: version drift (pyp...
- **Статус:** автоматически синхронизировано


## 2026-08-05 21:15 — Триаж KNOWN_ISSUES#2026-08-04-21:00 (Zed crash-loop) — цифры верифицированы замером

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial — loop остановлен (последний краш 08-04 21:27), риск сохраняется; дедлайн владельца 08-11
**Root Cause:** подтверждён: Zed commit 8.54GB при commit-лимите 18.5GB (свободно 1.14GB...
- **Статус:** автоматически синхронизировано


## 2026-08-05 — D1: schema-слой из Neuro-Symbolic спайка → CypherExecutor (архитектурное закрытие P-004, FIXED, не запушено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии; push — по команде владельца)
**Root Cause:** P-004 «разрыв валидации между слоями»: неизвестные label/rel (галлюцинация LLM: `MATCH (f:SERVICE)`) принимались...
- **Статус:** автоматически синхронизировано


## 2026-08-05 20:10 — C1-C4 Cypher-стек: 4 бага KNOWN_ISSUES#2026-08-05 (FIXED, не запушено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии; push — по команде владельца)
**Root Cause:** C1 — label/edge сравнивались точно (=/IN) в cypher_sql.py, лексер принимает любой регистр LABEL → тихий пустой р...
- **Статус:** автоматически синхронизировано


## 2026-08-05 — A2 (внешний аудит): sandbox threat model — ADR-0001 ✅ Accepted (Вариант A)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (решение по умолчанию, §1.10 — владелец не выбрал B/C; переопределение возможно)
**Root Cause:** внешний аудит: blacklist-модель sandbox принципиально обходима (чистый Python без ОС...
- **Статус:** автоматически синхронизировано


## 2026-08-05 01:50 — Tech debt: subprocess text=True без encoding ×7 закрыт + пин ruff (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (коммит в этой сессии)
**Root Cause:** text=True без encoding в 7 местах декодирует вывод через locale (cp1251/cp1252 на Windows) — UnicodeDecodeError при не-ASCII выводе (тот же кл...
- **Статус:** автоматически синхронизировано


## 2026-08-05 00:05 — CI красный: ruff I001 (10 импорт-блоков, НЕ coverage) (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит a7a7a9e7, запушен)
**Root Cause:** CI-прогоны b121ab19/6dc8d2ae упали на lint-шаге `ruff check src/ tests/` — 10 ошибок I001 (неотсортированные импорты) в 8 файлах: src/cor...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:59 — CI: кэш pip + coverage 41% (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** Next Action #9-#10: CircuitBreaker «dead» — ❌ REFUTED (подключён к embedder напрямую, di_container:337-345); coverage отсутствовал.
**Fix:** ...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:59 — Триаж bare-except: 4 рискованных silent-блока залогированы (PARTIAL)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 partial (коммит в этой сессии)
**Root Cause:** scan нашёл 106 silent-блоков (except → pass); большинство намеренные (CancelledError/таймауты/best-effort).
**Fix:** логирование в 4 местах...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:59 — Баг-клоуза: layer.py порт LM + резолв 7 VERIFY (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** из 3 аудитов остались VERIFY-пункты; единственный реальный баг — layer.py:504 хардкод порта LM Studio 1234 (рядом код уже читал порты из conf...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:58 — Hotfix: pickle P1 закрыт restricted unpickler'ом (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** index_guard.py:367 обычный pickle.load на legacy symbol_index.pkl — RCE-вектор (OWASP десериализация).
**Fix:** `_LegacyPickleLoader(pickle.U...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:50 — Глубокий аудит (2-й проход): верификация 26 пунктов (TRIAGE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 триаж завершён, фиксы запланированы (коммит в этой сессии)
**Root Cause:** второй внешний аудит (async, subprocess, BLE001, coverage, порты). Проверено по коду: create_task fire-and-forg...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:30 — Триаж внешнего ревью: 165 находок, тесты зелёные (TRIAGE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 триаж завершён, фиксы запланированы (коммит в этой сессии)
**Root Cause:** внешний инструмент нашёл 165 проблем; критические проверены по коду: SQL_INJECTION (graph.py x4) — ❌ ложные (па...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:00 — CI clean-state: No module named pytest (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** Linux-ветка verify_clean_state.sh ставила `pip install -e ".[dev]" --no-deps` — dev-зависимости (pytest и др.) не входят в requirements-lock....
- **Статус:** автоматически синхронизировано


## 2026-08-04 22:25 — scripts/monitor.py: UnboundLocalError avg_log (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** переменная `avg_log` присваивалась только в ветке фаз эмбеддинга (PHASE_EMBED/WRITING/IVF), а читалась в блоке «Тренд» при любой фазе — при ф...
- **Статус:** автоматически синхронизировано


## 2026-08-04 22:40 — test_job_history: изоляция от переиспользования tmp_path (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** JobHistoryStore пишет во внешний `<data_root>/projects/<hash>/metrics/job_history.json`, а pytest переиспользует temp-пути между запусками (с...
- **Статус:** автоматически синхронизировано

## 2026-08-05 23:30 — Реальный отбор audit.md: 16 предложений сверено с кодом + 5 экспериментов (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (документация; код не менялся — Danger Zone соблюдён)
**Root Cause:** audit.md содержал 16 предложений «внедрить», из которых 6 УЖЕ реализованы (Cypher-стек, 27/29 EdgeType, change ...
- **Статус:** автоматически синхронизировано


## 2026-08-05 22:15 — AutoDocUpdater коррумпировал README: 4 бага в _update_readme/_count_* (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** (1) `_count_tools`: `text.count()` на regex-строке как на литерале (`@mcp\.tool\("` со слешами) + скан только server_tools.py → всегда 0; (2) `_count_tests`: `count...
- **Статус:** автоматически синхронизировано

## 2026-08-06 21:10 — Workstreams A+B+C по отбору audit.md: SCM wiring, language-pack (+54), Leiden (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done — 853 passed / 4 skipped (baseline 831); ruff чист; коммиты: (A) SCM wiring, (B) language-pack, (C) Leiden
**Root Cause:** (A) вендоренные 17 tags.scm НЕ компилировались с установле...
- **Статус:** автоматически синхронизировано


## 2026-08-06 19:45 — Live-верификация 5 быстрых побед audit.md: 4/5 ✅, SCM-определения частично (wiring НЕ подключён), packaging-фикс

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial — packaging закрыт (коммит f14435db), wiring SCM ждёт решения владельца
**Root Cause:** «SCM-определения» реализованы на 70%: 17 tags.scm + `extract_definitions_scm`/`_load_tags_...
- **Статус:** автоматически синхронизировано


## 2026-08-06 22:05 — Протокол: Триггеры 6-7 (§1.19), оживлён §6.4, §0.1/§7 блокирующий task state, WISDOM.md (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done — глобальный AGENTS.md: Триггеры 6-7 (§1.19), §6.4 (Ledger-проверка каждой сессии), §0.1 п.2 (блокирующее обновление task state), §7 п.10 (DoD); создан WISDOM.md ≤50 строк; проектный AGENTS.md §0.6 + FIRST STEP
- **Статус:** автоматически синхронизировано


## 2026-08-06 — Protocol-compression: черновик AGENTS.compact.md (−57.7%) + мех-слой (PARTIAL, A/B pending)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial — сжатие глобального AGENTS.md: черновик −57.7% (14.9k токенов), мех-слой вернул §5.16 (Windows subprocess, 12+ ссылок), Living Memory → §5.24; EXPERIMENTS_LOG: exp: protocol-compression; A/B по §1 не запускался — поведенческая эквивалентность ⏳ PENDING
- **Статус:** автоматически синхронизировано

## 2026-08-06 22:35 — Закрытие находок вне скоупа A/B: sync-мосты удалены, счётчики 49 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+доки; 19 passed)
**Root Cause:** T1/T4 эксперимента были откатаны — реальные фиксы не применялись: 2 мёртвых sync→async bridge (0 вызовов) + устаревшие счётчики «37/48/19 core...
- **Статус:** автоматически синхронизировано


## 2026-08-06 23:05 — Закрытие «48/19 core»: AGENTS.md + ARCHITECTURE en|ru|zh → 49 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (docs-only; per-file grep-0 по 4 файлам)
**Root Cause:** счётчики «48/19 core» (ru/zh — даже «42»/«18 core»/«7 inline») в AGENTS.md + ARCHITECTURE en|ru|zh не обновлены после Detect...
- **Статус:** автоматически синхронизировано


## 2026-08-06 23:35 — Следующий шаг: «48/19 core»/«37»/«50» закрыты в README + ru/zh-доках + ZED (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (docs-only, 18 файлов, per-file grep-0)
**Root Cause:** те же устаревшие счётчики «48/19 core», «37 (19 core + 12 intel + 6 diag)», «42», «50 total» в ru/zh-переводах + README/ZED —...
- **Статус:** автоматически синхронизировано


## 2026-08-06 21:40 — A/B protocol-compression: ARM A (полная версия) — 54/64; ARM B ждёт Reload Zed

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial — arm A готов; arm B — сессия 2 (компакт); восстановление AGENTS.md после arm B обязательно
**Root Cause:** (контекст) компакт −57.2% (53054 B/486 строк); поведенческая эквивален...
- **Статус:** автоматически синхронизировано


## 2026-08-06 22:05 — Протокол: Триггеры 6-7 (§1.19), оживлён §6.4, создан WISDOM.md (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done — правки в глобальном `AGENTS.md` (профиль Zed, вне репозитория) + проектном AGENTS.md; WISDOM.md создан
**Root Cause:** три дыры замыкания петель: (1) §6.4 Ledger-проверка «раз в с...
- **Статус:** автоматически синхронизировано


## 2026-08-06 — Protocol-compression: черновик AGENTS.compact.md (−57.7%) + мех-слой (DONE, A/B pending)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial — объём подтверждён замером; поведенческая эквивалентность — A/B не запускался
**Root Cause:** 126KB/35k токенов AGENTS.md — «Lost in the Middle»-риск (Verified: arXiv:2307.03172...
- **Статус:** автоматически синхронизировано

## 2026-08-06 23:45 — LSP B+C: bridge деприцирован, 3 LSP-тула (basedpyright), счётчик 52 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+доки+тесты; 853 passed)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh (чистый клон) не запускался; перепроверено в рабочем дереве: pytest tests/ → 853...
- **Статус:** автоматически синхронизировано


## 2026-08-06 23:50 — Закрытие 3 открытых вопросов: ru/zh секции инструментов, edge-count 29, CONTRIBUTING 3.3.13 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (docs-only, 26 файлов; pytest 853 passed замер сессии)
**Root Cause:** (1) ru/zh README секции инструментов не прошли реструктуризацию после hub-миграции — легаси-имена (get_commit_...
- **Статус:** автоматически синхронизировано

## 2026-08-07 23:30 — Аудит Bot_snow остаток BS-1..BS-14: 14/14 закрыто (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 894→937 passed, +43 теста в tests/test_search_bs_audit.py)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; pytest tests/ → 937 pas...
- **Статус:** автоматически синхронизировано


## 2026-08-07 — Synthetic monitoring качества поиска: «не пусто?» → реальные результаты (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 894 passed / 4 skipped)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; перепроверено в рабочем дереве: pytest tests/ → 894 passed...
- **Статус:** автоматически синхронизировано


## 2026-08-07 — Инструменты с корнем через __file__: stale_detector/_grep_fallback сканировали расширение (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 884 passed / 4 skipped)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; перепроверено в рабочем дереве: pytest tests/ → 884 passed...
- **Статус:** автоматически синхронизировано


## 2026-08-07 — Multi-window MCP изоляция: CWD-first резолв (INC-MULTI-WINDOW) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 881 passed / 4 skipped)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh (чистый клон) не запускался; перепроверено в рабочем дереве: pytest tests...
- **Статус:** автоматически синхронизировано


## 2026-08-07 — LSP E: lsp_get_code_actions (quick fixes), счётчик 54→55 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 872 passed / 4 skipped)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; перепроверено в рабочем дереве: pytest tests/ → 872 passed...
- **Статус:** автоматически синхронизировано


## 2026-08-07 — LSP D: lsp_get_type_info + lsp_get_diagnostics + pre-flight в WriteTool, счётчик 52→54 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 866 passed / 4 skipped)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh (чистый клон) не запускался; перепроверено в рабочем дереве: pytest tests...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Эксперимент: Multi-Tool vs Context Engine (CodeGraph-стиль) (DONE, исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (read-only эксперимент, src/ не менялся; EXPERIMENTS_LOG#2026-08-08-context-engine)
Агрегатор get_edit_context-стиля: −78% tool_calls, −89% latency, −19% tokens, паритет task success (84.5% vs 88.1%), wrong-context 13% vs 15.5%. Условия: source+symbols во всех intent; память файл-скоуп; impact_analysis «not found» на приватных символах.
- **Статус:** автоматически синхронизировано

## 2026-08-08 — Эксперимент D (v2): Context Composition vs Tool Composition (DONE, исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (read-only эксперимент, src/ не менялся; EXPERIMENTS_LOG#2026-08-08-context-engine-v2)
15 задач, 4 руки: C2 (реальный get_edit_context) recall 0.817 > A 0.783, precision 0.705 > 0.667, 1 RT/865ms vs 3.4 RT/1583ms; C1 (существующий get_context) recall 0.267 — недостаточен; токены C2 1231 vs A 241 (нужен token budgeting); wrong-definition build_call_graph штрафует все руки.
- **Статус:** автоматически синхронизировано

## 2026-08-08 — Эксперимент D v3: 30 задач — B vs C2 устойчивость (DONE, исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (read-only, src/ не менялся; EXPERIMENTS_LOG#2026-08-08-context-engine-v3)
30 задач, paired-статистика: recall B vs C2 неразличимы (Δ +0.025, CI95 ±0.054, ничьи 27/30), precision C2 не значимо (+0.036 ± 0.047), токены B стабильно ниже (~980, CI95 ±249, 30/30). Вывод: B-подход (intent-фильтр) = оптимум (recall 0.900 ≥ A 0.875, 1 RT, 275 токенов); расширять get_context по B-схеме, не полный C2.
- **Статус:** автоматически синхронизировано

## 2026-08-13 20:40 — Унификация путей хранения + ArtifactGC + защита диска + фикс тестов (DONE, 1125 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ полный `python -m pytest tests/ -q` → 1125 passed / 4 skipped / 94 deselected (2026-08-13); ru...
- **Статус:** автоматически синхронизировано


## 2026-08-13 20:05 — P2-фикс: extract_anchors валидация якорей на write-path (DONE, 1113 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `python -m pytest tests/ -q` → 1113 passed / 4 skipped (2026-08-13); ruff check на 3 изме...
- **Статус:** автоматически синхронизировано


## 2026-08-13 19:35 — Аудит project memory: VOR работает, 2 ложных авто-отзыва закрыты пересохранением, 1 устаревший узел суперседирован (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (память приведена в порядок; мутации — через MCP-инструменты; файл памяти вне git)
**verified_from_clean_state:** ✅ да — повторный дамп 36 узлов (5 VERIFIED / 24 ACTIVE / 6 REFUTED...
- **Статус:** автоматически синхронизировано


## 2026-08-13 19:10 — Глобальный AGENTS.md: §5.24 семантическая память + Red Team (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (C:\Users\misha\AppData\Roaming\Zed\AGENTS.md — вне репозитория)
**verified_from_clean_state:** ⚠️ полный clean-state неприменим (файл вне git); проверено: assert-якоря count==1 ×3...
- **Статус:** автоматически синхронизировано


## 2026-08-12 04:00 — v1-спека памяти закрыта + ADR-0004 Propagation Engine (DONE, не закоммичено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VERIFICATION: PASSED, exit 0, 1099 passed / ...
- **Статус:** автоматически синхронизировано


## 2026-08-12 01:00 — FIX P2 canary (fail-closed + abs-порог + collapse-детектор), P3 health (eligible_seen), doc-sync 117 дрейфов → stale_detector RE-ENABLED в pre-commit (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; test_shadow_canary 13/13, test_search_quality_monitoring 12/12, pre-commit hook RC=0; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ yes — `p...
- **Статус:** автоматически синхронизировано


## 2026-08-11 23:59 — RESEARCH dev.to верификации AI-агентов: 5 экспериментов + 2 живых «guard не может упасть» (DONE, внедрение ждёт решения)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (5 экспериментов выполнены с raw output — EXPERIMENTS_LOG#2026-08-11-EXP-1..5; правок в src/ НЕТ — research base по §1 Шаг 4)
**Root Cause:** класс Тома ln.strip() подтверждён Д...
- **Статус:** автоматически синхронизировано


## 2026-08-11 23:55 — Exp 1-V REPLICATION: verify-on-read подтверждён на независимых данных (facts v4) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (эксперимент выполнен, EXPERIMENTS_LOG#2026-08-11-1-V-REP; код-изменений вне experiments/ нет — только параметризация пути фактов в verify-скрипте)
**Root Cause:** — (Правило од...
- **Статус:** автоматически синхронизировано


## 2026-08-11 22:10 — ADR-0002 RetractionReceipt: intel_retract_memory_node + статус-модель (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты+доки; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VERIFICATION: PASSED, ...
- **Статус:** автоматически синхронизировано


## 2026-08-11 22:40 — Exp 1-R: ретракция измерена — persistent contamination -88%, memory_first 1.0→0.12 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (эксперимент выполнен, EXPERIMENTS_LOG#2026-08-11-1-R; код-изменений вне experiments/ нет)
**Root Cause:** — (измерение эффекта ADR-0002; контрольная группа = v3, parity OK: ado...
- **Статус:** автоматически синхронизировано


## 2026-08-11 23:10 — ADR-0003 Verify-On-Read: Lazy Validation Layer, adoption честного → 0.0 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты+эксперимент; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VERIFICATION: P...
- **Статус:** автоматически синхронизировано


## 2026-08-11 23:50 — ADR-0003 follow-up: write-time anchor capture в intel_add_memory_node/auto_collect_adrs (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VERIFICATION: PASSED, exit ...
- **Статус:** автоматически синхронизировано


## 2026-08-11 21:15 — FIX: get_context интенты git_history/verify_change возвращали пусто

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (закоммичено локально, не запушено; tests/test_context_tool.py 2 passed, ruff чист)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN ST...
- **Статус:** автоматически синхронизировано


## 2026-08-11 22:40 — Experiment 1: Memory Contamination (IntelligenceStore) N=24 (DONE, исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (read-only к src/; EXPERIMENTS_LOG#2026-08-11-memory-contamination; изоляция: store_dir tempdir ≠ реальный, подтверждено assert'ом и полем isolation)
**Root Cause:** — (не инцид...
- **Статус:** автоматически синхронизировано


## 2026-08-11 21:45 — FIX: hybrid_search_async кэш-хит терял vector-тир

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (закоммичено локально, не запушено; gate-zero 1025 passed/10 skipped, ruff 0)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VE...
- **Статус:** автоматически синхронизировано


## 2026-08-11 — Experiment 1: Multi-RAG Component Ablation N=30 (DONE, исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (read-only эксперимент, src/ не менялся; EXPERIMENTS_LOG#2026-08-11-multi-rag)
**Root Cause:** — (не инцидент; проверка статьи «Multi-RAG > Single RAG»): recall-максимум даёт ft...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Фикс D1-D3: единый корень — неранжированный выбор узла в графе

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ⚠️ Fixed (локально: gate-zero 1031 passed / 4 skipped, ruff src/ tests/ = 0; +4 регресс-теста tests/test_graph_adapter_node_selection.py)
**verified_from_clean_state:** ✅ yes — `bash scrip...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Повторная верификация deep-research-report(1).md: 25 пунктов, 10 ❌ (исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (исследование, код не менялся; Ledger закрыт в .agent_task_state.md)
**Root Cause:** — (не инцидент; верификация аудита): 25 утверждений отчёта сверены с текущим кодом. Верно: C...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Реализация 4 фиксов аудита: mutex, TaskQueue, LanceDB rollback, transformers-pin (DONE, 1026 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 1022→1026 passed / 4 skipped / 94 deselected, ruff check src/ tests/ = 0)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; pytest t...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — F3 остаточный риск закрыт: rollback и reset_connection сериализованы единым lock (DONE, +1 тест)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (тест; 9/9 test_lancedb_recreate, ruff чист; полный прогон 1027 passed — 1 транзиентный фейл test_connection из-за живого MCP, повтор зелёный)
**verified_from_clean_state:** ⚠️ не ...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Координационный инцидент: git commit без pathspec украл staged-правку параллельной сессии (RESOLVED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Resolved (история не переписана — 568b1f27 уже в origin; урок в WISDOM)
**verified_from_clean_state:** ⚠️ не проверено — docs-коммит; CI-ран ad1a6d2d — 7/7 success
**Root Cause:** две се...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — PYSEC-2026-3552: cryptography 49.0.0 в lock → 50.0.0 + pip-audit в CI (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (lock-bump + CI-гейт; pip-audit: No known vulnerabilities found; ci.yml YAML валиден)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не гонялся (изменения в...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — CI-механический guard в AGENTS.md §7 + code-scanning алерты 22/24 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (доки+тесты; ruff check src/ tests/ = 0, TestAuditLog 2 passed)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh (чистый клон) не запускался; pre-commit gate-...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — CI: version-compat фейлы на 3.10-3.12 (tomllib/read_text-newline/UNC) (FIXED, matrix локально зелёный на 3.10+3.11)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 3.10: 995 passed / 10 skipped, 3.11: 1000 passed / 5 skipped, coverage 46.6% > 38; ruff чист)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh пос...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — CI ubuntu: test_normalize_diag_uri без Windows-skip (FIXED, CI зелёный на 3.10/3.11/3.12 + clean-state)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; ruff чист; ubuntu-фейлы 2 шт на ВСЕХ версиях + clean-state — одна причина)
**verified_from_clean_state:** ✅ да — CI-прогон #247 (5a771789): 7/7 джобов success (windows+...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — CI красный 18 прогонов (#226-#243): lint 35 ошибок + clean-state ubuntu (FIXED lint, clean-state pending)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (lint: 35 ошибок → 0; matrix-команда: 1005 passed / 4 skipped / 94 deselected, coverage 46.76% при гейте 38%) | ⏳ clean-state ubuntu — не воспроизводится локально, ждёт лог CI
**ve...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Следующий шаг: verify_clean_state Windows-ветка + unclosed transport (DONE, 1005 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; -X dev 1005 passed / 4 skipped / 94 deselected; ruff чисто)
**verified_from_clean_state:** ✅ РЕАЛЬНЫЙ прогон `bash scripts/verify_clean_state.sh --no-clone` на Windows ...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — WS9: PID-lock self-healing (вариант C) — orphan/зомби-детекция + soft-wait 8s + psutil-вывод (DONE, 1022 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 1005→1022 passed / 4 skipped / 94 deselected, ruff чист; НЕ запушено)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался (код не в CI-...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — WS8 boot fix: llama deferred после stdio (MCP "Context server request timeout" на холодном старте) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код; 1005 passed / 4 skipped; проверено LIVE: бут 12s, BUILD_ID = коммит f73be307eeb1)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; pytest...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — WS7 Security Hardening: trust-стампинг, instruction-флаги, tool-guard (DONE, 1005 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 990→1005 passed, +15 тестов; runner benchmark2: 20 задач; активация MCP после Reload Window)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не з...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — WS1-WS6 roadmap: consistency, trust, late enrichment, Execution Contract 2.0 (DONE, 990 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 956→990 passed, +34 теста; 2 эксперимента в EXPERIMENTS_LOG; активация MCP после Reload Window)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh н...
- **Статус:** автоматически синхронизировано


## 2026-08-08 02:15 — 1-2-3: доки 57/58, AsyncMock-фикс sleep-корутин, verify_clean_state (DONE, 990 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (1-2) | ⚠️ Task 3: verify_clean_state.sh не запускается на Windows GitBash (POSIX venv/bin vs Windows venv/Scripts, exit 127) — CI-only; локальный эквивалент: pytest tests/ 990 pas...
- **Статус:** автоматически синхронизировано


## 2026-08-08 01:30 — Верификация внешнего аудита (ChatGPT): 14/15 утверждений подтверждено, полный реиндекс 5205 чанков (DONE, 956 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (код не менялся — исследовательская сессия по запросу владельца; полная переиндексация выполнена)
**Root Cause:** — (не инцидент; сверка внешнего аудита vs локальный код + внешн...
- **Статус:** автоматически синхронизировано

## 2026-08-14 09:00 — P1 CI: digest-pinning CRLF-sensitive — инвентарь UNPROVEN x3 на ubuntu (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (commit + push; CI зелёный после фикса)
**verified_from_clean_state:** ✅ да — CI ubuntu matrix зелёный после фикса (gh run watch); локально 12/12 тестов, hook 4/4
**Root Cause:** _...
- **Статус:** автоматически синхронизировано


## 2026-08-14 08:40 — pre-commit hook + negative_controls runner + коммит сессии (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (commit сделан; не запушено — push по команде)
**verified_from_clean_state:** ✅ да — pre-commit hook 4/4 (verify_diary / stale_detector / check_tool_names / negative_controls); run...
- **Статус:** автоматически синхронизировано


## 2026-08-14 08:05 — Red team round 2 (TC-7..TC-10) + runner hardening: provocation_type, --pin --reason, pin_log, transitive fixtures (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты+RFC; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → PASSED, 1160 passed / 0 failed (вкл...
- **Статус:** автоматически синхронизировано


## 2026-08-14 07:30 — Guard Inventory (OWP §5.2, P3 research 08-11): scripts/negative_controls_runner.py + привязка отчётов к git HEAD (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VERIFICATION: PASSED, 1157 ...
- **Статус:** автоматически синхронизировано


## 2026-08-14 11:45 — Guard проза-«import X» (C-гибрид): частотное слово без src-импорта ≠ якорь (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты+ADR; не закоммичено — commit/push)
**verified_from_clean_state:** ✅ да — полный pytest tests/ 1149 passed / 10 skipped (102s) + `bash scripts/verify_clean_state.sh --no-...
- **Статус:** автоматически синхронизировано


## 2026-08-14 11:15 — Live-smoke поймал ложный отзыв: проза-«import path» → REFUTED собственного ADR-узла (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (данные памяти восстановлены; код-гвард — OPEN вопрос владельцу)
**verified_from_clean_state:** ✅ да — полный pytest tests/ 1143 passed / 10 skipped (92s) + `bash scripts/verify_cl...
- **Статус:** автоматически синхронизировано


## 2026-08-14 10:45 — ADR-0005 pkg:-анкоры (closed-world манифест) + верификация поста dev.to (DONE, 68 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты+ADR+KNOWN_ISSUES; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1143 passed / 10 skipped (92s, 202...
- **Статус:** автоматически синхронизировано


## 2026-08-13 23:55 — VOR-ресипт: checked/total в intel_get_project_memory (пол Тома) (DONE, 1142 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1142 passed / 4 skipped (2026-08-13); LSP-diagnosti...
- **Статус:** автоматически синхронизировано


## 2026-08-13 23:20 — Фикс job-чанков (фильтр embed-лога) + LIVE-SMOKE скрипт + правило §7 (DONE, 1135 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+скрипт+доки; коммиты 7b38f50a + следующий)
**verified_from_clean_state:** ✅ да — полный pytest 1135 passed / 4 skipped (2026-08-13); `python scripts/smoke_e2e.py --project .` ...
- **Статус:** автоматически синхронизировано


## 2026-08-13 20:45 — FIX А2: сервер снова отвечает во время/после индексации (sync update_all → to_thread) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тест; не закоммичено — commit/push по команде; сервер мёртв — нужен Reload)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1134 passed / 4 skipped...
- **Статус:** автоматически синхронизировано


## 2026-08-13 20:20 — Демонстрация инструментов + 2 аномалии: файл невидим для поиска, full-reindex блокирует MCP (OPEN)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial (демонстрация выполнена; аномалии зафиксированы, root cause P1 не установлен)
**verified_from_clean_state:** ⚠️ не проверено (демонстрация, код не менялся) | **Root Cause:** (А1)...
- **Статус:** автоматически синхронизировано

## 2026-08-14 09:35 — P1 CI: revision_gate UNKNOWN на shallow-checkout — clean-state красный (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит + push; CI-проверка после)
**verified_from_clean_state:** да — локально revision gate VALID (38f4be7d >= min 815222828cf6); CI после фикса — watch
**Root Cause:** CI (actio...
- **Статус:** автоматически синхронизировано


## 2026-08-14 09:20 — Испытание инструментов: stale_detector MCP-тул — 11 ложных дрейфов; + revision_gate (TC-9) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не запушено — push по команде)
**verified_from_clean_state:** ✅ да — verify --no-clone PASSED (1170 passed); делегированный скан 0 дрейфов; revision gate VALID
**Root C...
- **Статус:** автоматически синхронизировано

## 2026-08-15 23:50 — Exp 2-E Evidence Ladder E1+E2+E3: форма evidence решает, но не для всех моделей (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Завершено (450 вызовов OpenRouter, $0.007; builder graph_context + arm graph_first + 48 тестов)
**Root Cause:** «структурное evidence ≠ автоматически лучше»: граф закрывает present-trap ...
- **Статус:** автоматически синхронизировано


## 2026-08-15 23:55 — Exp 2-E E3b+E4: гибрид НЕ аддитивен; git-провенанс работает у 2/3 моделей (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Завершено (294 вызова, $0.007; temporal_facts_generator + temporal contexts + arm'ы file_graph_first/temporal_first, 56 тестов)
**Root Cause:** (1) гибрид file+graph НЕ аддитивен: qwen3....
- **Статус:** автоматически синхронизировано


## 2026-08-16 00:30 — RED TEAM 2-E: 4/6 trap-фактов v4_rep истинны → выводы E3 инвертированы (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Завершено (атака на ground truth; corrected-матрица; pytest 1265 passed; --pin-provider в harness; отчёт + статья)
**Root Cause:** генератор trap-фактов проверял `value != real_value` су...
- **Статус:** автоматически синхронизировано


## 2026-08-16 — CI-фикс zed_config: PYTHONPATH с Windows-путём на POSIX-раннере (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код; POSIX-верификация — CI-матрица после пуша)
**verified_from_clean_state:** ⚠️ не проверено (POSIX-сторона — CI после пуша); локально (Windows): 8 passed + PurePosixPath-симуля...
- **Статус:** автоматически синхронизировано


## 2026-08-16 — DocGenerator: dist/build в docs-выдаче (инцидент infrawise) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; live: infrawise — dist исчез из выдачи)
**verified_from_clean_state:** ⚠️ не проверено полным прогоном (затронутые 111 passed + live: DocGenerator(infrawise) → dist abs...
- **Статус:** автоматически синхронизировано


## 2026-08-16 — gitignore_parser: dir-семантика паттернов (мёртвая ветка → git-корректно) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ⚠️ не проверено полным прогоном (затронутые: gitignore 5 + doc_generator 2 + FileGuard/индексато...
- **Статус:** автоматически синхронизировано


## 2026-08-15 23:35 — Аудит обновлений Zed 1.12–1.16: код почти не затронут, 3 точечные подстройки (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (3 файла: цены харнесса, guard-тест схем, AGENTS.md заметка; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ⚠️ не проверено; полный pytest 1248 passed / 10...
- **Статус:** автоматически синхронизировано


## 2026-08-15 11:09 — Exp 1-L V4: file_content_first — закрыта «точка укуса №2» (anchor bias, не паранойя) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (харнесс+тесты+live-прогон 100 выз.; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ⚠️ не проверено (полный pytest не гонялся; 39/39 на затронутых тестах h...
- **Статус:** автоматически синхронизировано


## 2026-08-15 00:45 — Exp 1-L Day 3: ответ на ревью Part 4 — per-category метрики + V3/Part 5 CoT vs Zero-Shot (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (доки+скрипты+тесты+live-прогон; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ⚠️ не проверено (полный pytest не гонялся; 38/38 на затронутых тестах harne...
- **Статус:** автоматически синхронизировано


## 2026-08-14 23:20 — Exp 1-L Day 2: свип 6 дешёвых моделей OpenRouter — эксперимент доделан (COMPLETED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Completed (код+тесты+данные; commit/push по команде)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1216 passed / 10 skipped; live: 600 реальных вызовов Open...
- **Статус:** автоматически синхронизировано


## 2026-08-14 23:55 — Red Team атака на Exp 1-L: seed не детерминирует на OpenRouter (±0.05–0.10 FA) (FINDING)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Проверено (2 полных прогона × 600 вызовов; правки+тесты; данные в progress-файлах)
**verified_from_clean_state:** ✅ да — `python -m pytest tests/ -q` → 1226 passed / 10 skipped; live: 12...
- **Статус:** автоматически синхронизировано


## 2026-08-14 21:30 — Полный живой аудит MCP: телеметрия заражена общим tool_metrics.json (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; commit/push ниже)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1198 passed / 10 skipped; живые вызовы: search_code 177ms / graph_query 27...
- **Статус:** автоматически синхронизировано


## 2026-08-14 16:20 — Фикс 11 дыр в градере реранкера по evalmut-методологии (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1189 passed / 10 skipped (93s); ruff clean на 3 изм...
- **Статус:** автоматически синхронизировано


## 2026-08-14 15:55 — evalmut-перенос: мутационный аудит validate_scores — 11 дыр в градере реранкера (FOUND → FIXED 16:20)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (фикс — запись 16:20; 1189 passed, mutation score 100%)
**verified_from_clean_state:** ✅ да — полный pytest 1189 passed / 10 skipped (2026-08-14 16:20), experiments/evalmut/probe_e...
- **Статус:** автоматически синхронизировано


## 2026-08-14 11:15 — Ревью Part 3: серийная навигация Field Notes + 1-M (маппинг, закрыт) + 1-L (дизайн с live-model arm) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (доки+скрипт; не запушено — push по команде)
**verified_from_clean_state:** ✅ да — коллектор дал реальный снимок (51 узел, false_retraction 12.5%, rev 1fdb2e4e); ruff чист
**Root C...
- **Статус:** автоматически синхронизировано


## 2026-08-14 10:05 — P2 health: «99 ошибок в логе» — подстрока count("error") вместо level-маркеров (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; push)
**verified_from_clean_state:** ✅ да — 6 тестов (log_levels 3 + fs_sync 3); ruff чист; реальный лог: 20 [ERROR] vs 99 по подстроке
**Root Cause:** _check_logs счит...
- **Статус:** автоматически синхронизировано


## 2026-08-14 09:50 — P2 health: «273 orphan» — артефакт среза rglob на venv/ (22k файлов) (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; push)
**verified_from_clean_state:** ✅ да — реальный скан 800 путей (было 23934 с обрывом на 10001); тесты 3/3; CI watch после push
**Root Cause:** health._check_filesy...
- **Статус:** автоматически синхронизировано

## 2026-08-18 — monitor.py: мониторинг ЛЮБОГО проекта (--project/--data-root/--log + self-bootstrap) (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ внесено и проверено (ruf: 7 < baseline 8, без новых; --help ок; резолв пути подтверждён; не закоммичено)
**Root Cause:** monitor.py жёстко читал единственный глобальный лог и не имел CLI...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Верификация ARCLUX-отчёта по протоколу: 10 пунктов, 6 FP/стале, 2 реальных фикса, 3 pre-existing (FIXED 2)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ 2 фикса внесены и проверены (не закоммичено — на параллельной ветке лежат чужие правки engine.py/test_search_bs_audit.py)
**Root Cause/Итог:** Из 10 пунктов отчёта: (1) цикл error_handle...
- **Статус:** автоматически синхронизировано


## 2026-08-17 — ARCLUX audit: core→mcp импорт и graph.py self-import (FIXED); кластер MCP-циклов (OPEN)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (1294 passed; linter 0 [CORE_MCP]; ruff clean; guard — в дефолтном CI)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не гонялся (нет сети/URL); локально: п...
- **Статус:** автоматически синхронизировано


## 2026-08-17 — ARCLUX: кластер циклов MCP разорван гибридом A+B (src/mcp/context.py) (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (E1: SCC 19→0, рёбер в циклах 77→0; linter TOOL_REGISTRY 4→0; pytest 1294 passed; ruff clean; import-time без роста; не закоммичено — прототип)
**verified_from_clean_state:** ⚠️ не...
- **Статус:** автоматически синхронизировано


## 2026-08-16/17 — P1 propagation_engine невидим для поиска: H1/H2 ОПРОВЕРГНУТЫ, ЗАКРЫТ перезапуском процесса (✅)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Закрыто (2026-08-17, live-подтверждение после Reload Window)
**Root Cause:** НЕ дефект индексации — in-memory поисковые структуры ЖИВОГО процесса не подхватывали обновление индекса, пока...
- **Статус:** автоматически синхронизировано


## 2026-08-17 — Поиск: doc-чанки не вытесняют код (Вариант A → A', отбор кандидатов)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (юнит 48 passed; live-подтверждение после Reload — код процесса не хот-релоадится)
**verified_from_clean_state:** ⚠️ не проверено — clean-clone не гонялся; локально: юнит 48 passed...
- **Статус:** автоматически синхронизировано


## 2026-08-16 — Аудит документации, проход 2: ОПИСАНИЯ (не только числа) — системный дрейф embedder-нарратива (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (README ×3 + ARCHITECTURE + ARCHITECTURE_DEEP + GRACEFUL_DEGRADATION + TELEMETRY + INSTALL + FAQ + SEARCH_PIPELINE + tools_reg; не закоммичено — commit/push по команде)
**verified_...
- **Статус:** автоматически синхронизировано



## 2026-08-18 — MCP баг-хэунт: deep/auto подменялись grep-fallback (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (регрессионный тест + отрицательный контроль; live после Reload: deep → 6 реальных результатов)
**Root Cause:** в SearchCodeTool.execute (search_tools.py) results_count ставился только в fast/quality; str-режимы (deep/context/ask/auto) давали results_count=0 → grep-fallback подменял реальный результат.
**Fix:** `if results_count == 0 and isinstance(raw, dict):` — grep-fallback только для dict-режимов. Guard: test_next_step_hints.py::TestSearchCodeDeepNotClobbered.
- **Статус:** автоматически синхронизировано


## 2026-08-18 — monitor.py: не показывал живую переиндексацию (читал лог, а не progress.json) (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (read_progress_json как приоритет; лог — фолбэк)
**Root Cause:** после job-manager per-chunk-строки индексации идут в progress.json, а не в лог; monitor парсил лог → устаревшее «Завершено 9146» при идущей переиндексации.
**Fix:** читать progress.json (get_progress_file) как живой источник (phase/progress/total/current_file/ETA).
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Аномалия «pytest --collect-only → 5 tests»: fd-capture ValueError при rootdir-обходе (DIAGNOSED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 диагностировано; рабочее решение — `pytest tests/` (1398), fixes
**Root Cause:** bare `pytest` (из корня) падает с `ValueError: I/O operation on closed file` в `_pytest/capture.py:591` на широком rootdir-обходе в venv (Python 3.14 + pytest 9.1.1). `pytest tests/` работает (1398). Баг окружения/pytest, не кода.
**Fix:** hygiene: `experiments` → `norecursedirs` (pyproject.toml). Полный фикс bare-краша — отдельно.
- **Статус:** автоматически синхронизировано

## 2026-08-18 — Sandbox escape: `_builtins.__dict__['open']/['eval']` обходил validate_code (FIXED, не закоммичено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (локально, тесты 42 passed; commit по команде)
**Root Cause:** validate_code: Layer-1 строки обходятся конкатенацией (`'o'+'pen'`); Layer-2 AST не проверяет func=ast.Subscript, атр...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Все runtime-зависимости запинены (unpinned-dependency, 38 шт.) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ внесено и проверено (закоммичено d4e7cfe3)
**verified_from_clean_state:** ⚠️ не проверено (чистый clone не гонялся); локально: tomllib-парс 43 deps + marker-оценка 3.10/3.14 (packaging) ...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — MCP баг-хэунт: deep/auto подменялись grep-fallback (FIXED, подтверждено live после Reload)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (регрессионный тест + отрицательный контроль; live после Reload: deep → 6 реальных результатов)
**verified_from_clean_state:** ⚠️ не проверено (чистый clone не гонялся); регрессион...
- **Статус:** автоматически синхронизировано

## 2026-08-19 — Координационный инцидент: commit без pathspec утащил staged-правки парал-агента (RESOLVED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🔴 Fixed (зафиксировано; история не переписывалась)
**verified_from_clean_state:** ⚠️ не проверено — git-операции с локальной историей; воспроизводимо через `git --no-pager log --oneline -1...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — B-1: фаза 1 полная + фаза 2 stdlib lockfile'ы (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (src/sources/manifest/ 8 экосистем + 8 lockfile-экстракторов; pytest 1423; ruff clean на моих файлах; pre-commit 5/5)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — Фаза 4-хвост: wiring плагинов в MCP-сервер (PARTIAL, live deferred)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial (unit-зелёный; live smoke отложен на idle/CI)
**verified_from_clean_state:** ⚠️ не проверено — live create_mcp_server с плагином не гонялся (2-й MCP/PID-lock) — на idle/CI; unit ...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Фаза 3: Streamable HTTP транспорт начат (remote_main) (DONE, шаг 1-3)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (5 тестов auth/healthz/mount; полный pytest 1339 passed)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); локально: 5 тестов + полный pytest 1339 passed, ru...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — DNS-rebinding-детект (Фаза 2.5, SSRF) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (git_url 14 + upload 9 = 23 точечных; ruff clean; gate 0)
**verified_from_clean_state:** ⚠️ не проверено (полный pytest деградирован внешним клоном); локально: 23 точечных passed, ...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — UploadSource (Фаза 2, R-3) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (33 точечных теста; pytest 1324 байзлайн + внешний фейл клона)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone + full pytest заблокированы внешним клоном e-s1-polygon);...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — E-08 live SSRF-suite (9/9) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (e08_ssrf_suite.py 9/9 PASSED; коммит через --no-verify — см. ниже)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone + full pytest заблокированы внешним клоном исследова...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — MCP-тул index_git_url (Фаза 2 обвязка) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (pytest 1324 passed / 10 skipped; закоммичено e4bc051f на feat/universal-engine, push по команде)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); локально:...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — E-03 + clone-in-place fix (Windows rename-lock) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (E-03 4/4 PASSED; pytest 1321 passed; закоммичено 76b2991b + e01d1cce на feat/universal-engine, push по команде)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гоня...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Фаза 0 Universal Engine: adapters/ создан, Windows/Zed-специфика вынесена (DONE, не закоммичено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (pytest 1300 passed / 10 skipped; закоммичено 7232a6e2 на feat/universal-engine, push по команде)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); проверено...
- **Статус:** автоматически синхронизировано


## 2026-08-24 — Live Sync: editor RAM → демон (all-IDE, out-of-the-box)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Feature
**Root Cause:** FS-watcher бесполезен — IDE держит изменения в RAM до save; текущий `notify_change` VFS-путь мёртв (`src.hybrid_server` удалён 2026-07-20).
**Fix:** новый пакет `...
- **Статус:** автоматически синхронизировано

## 2026-08-24 — predict_change (MCP) + git-локи параллельных агентов (ADR-0007)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Feature (subset 34 passed; ruff clean; полный pytest — через pre-commit)
**Root Cause:** (1) Change Preview жил только в CLI — агент не мог звать предиктор как MCP-инструмент; (2) две го...
- **Статус:** автоматически синхронизировано


## 2026-08-24 — Change Preview (Фаза 1+2) + импорт-граф 56 языков (Вариант A)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Feature (24 новых теста; ruff clean)
**Root Cause:** (1) «точно знать что будет»: были impact_analysis (статический blast radius) и ActionReceipt (вердикт постфактум), но НЕ было связки ...
- **Статус:** автоматически синхронизировано


## 2026-08-24 — Architecture linter: STALE-ложности убраны, 4-й инвариант (циклы core) реализован и вшит в CI/pre-commit

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (linter exit 0; 4/4 invariant-тестов; ruff clean)
**Root Cause:** (1) STALE-паттерн «get_project_context(» матчил новое имя `intel_get_project_context(` как подстроку → 2 ложных ср...
- **Статус:** автоматически синхронизировано

## 2026-08-25 — Полный заморозок MCP при full reindex: root cause НЕ search, а get_status() на loop-потоке

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; pytest полный 1512 passed; ruff clean; commit b03073c5 был только симптом-патч search)
**Root Cause:** `IndexProjectRunner.run()` держит `db_manager._write_lock` (RLock...
- **Статус:** автоматически синхронизировано


## 2026-08-26 — Multi-window project-binding: search_code/graph_query/intel_* игнорируют project_root (set_project vs CWD-привязка)

- **Источник:** AGENT_DIARY.md (2026-08-26 19:55) + INVESTIGATION_MCP_PROJECT_BINDING.md
- **Описание:** **Status:** ✅ Fixed (scope 🅳+🅲+🅵+🅰+🅱; 🅴 подтверждён в коде)
**Root Cause:** search_tools.py звал resolve_searcher() без explicit project_root; graph_query/intel_get_project_memory не принимали project_root; reindex оставлял реестр UNINITIALIZED.
**Fix:** 🅳 base.py:resolve_indexer роутит explicit→active (уже было). 🅰 search_tools.py: _pr проброшен во все resolve_searcher/_project_header + _agentic_search. 🅲 intel_get_project_memory строит IntelligenceStore(project_root) с fallback. 🅵 покрыто 🅳. 🅴 layer.py:794-818 set_state(READY). 🅱 graph_tools.py: execute()+_execute_* пробрасывают project_root; добавлен _resolve_pg(); убран hardcoded D:/Project/MSCodeBase в drift/verify; structural_search уже имеет обязательный project_root. Синхронизировано в расширение.
**Guard:** tests/test_graph_query_project_binding.py (2 passed) + обновлены фейки test_search_bs_audit.py (3 passed).
- **Статус:** ✅ Fixed (2026-08-26; live-check не гонялся — требует multi-project+llama.cpp; проверит пользователь через Android-сервер)

## 2026-08-26 21:00 — DatabaseLock ORPHAN-kill → A+ fail-closed (PID 20052 killed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; live-smoke PASSED; exp2 holder survived)
**Root Cause:** `DatabaseLock.classify_holder()` возвращал `ORPHAN` для ЖИВОГО MCP чужого окна (parent-chain walk обрывался на ...
- **Статус:** автоматически синхронизировано


## 2026-08-26 19:19 — SymbolIndex JSON corruption guard live + E4.2 concept-resolver (verify_change 0→HIT)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (guard, live) / ✅ E4.2 подтверждена (live same-run: recall 0.50, verify_change 0→1.00)
**Root Cause:** (guard) `SymbolIndexAdapter` (graph-backed) без `_definitions/_references/_fi...
- **Статус:** автоматически синхронизировано


## 2026-08-25 — Research: mechanical orchestration without LLM — tool boundary (Exp M1-M3)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Research done (no src/ changes; experiments + Red Team + recommendation in EXPERIMENTS_LOG M1-M3)
**Root Cause (объект исследования):** 62 MCP-инструмента — большинство мёртвый груз: тел...
- **Статус:** автоматически синхронизировано


## 2026-08-25 — Вариант А: честный reindex-статус для агента (вместо вранья «0 chunks»)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (live-верификация полного reindex: MCP отвечал мгновенно весь прогон; pytest 1518 passed; ruff clean)
**Root Cause:** после фикса заморозки осталась ложь в сообщениях: (1) `intel_g...
- **Статус:** автоматически синхронизировано


## 2026-08-25 — Косметика live: reindex ToolError терял retry-семантику (двойная обёртка) + Project State INDEXING после авто-индекса

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (оба; pytest полный 1521 passed; ruff clean)
**Root Cause:** (1) reindex-ToolError из require_ready_project ловился общим `except Exception` и заворачивался в «Failed to check inde...
- **Статус:** автоматически синхронизировано


## 2026-08-26 19:55 — Multi-window: search_code/graph_query/intel_get_project_memory игнорируют project_root (set_project vs CWD-привязка)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (scope: 🅳+🅲+🅵+🅰+🅱; 🅴 подтверждён в коде)
**Root Cause:** search_tools.py вызывал `resolve_searcher()` без explicit project_root; graph_query и intel_get_project_memory не принимали...
- **Статус:** автоматически синхронизировано


## 2026-08-27 21:30 — MCP freeze during full reindex = logging deadlock (не CPU/не crash)

- **Источник:** AGENT_DIARY.md
- **Описание:** **verified_from_clean_state:** ✅ live — full reindex  embed-phase без заморозки сервера (QueueHandler/QueueListener); py_compile чист; pytest 1553 passed. Reindex доведён restart-ом (отдельный pre-exi...
- **Статус:** автоматически синхронизировано


## 2026-08-27 21:30 — off-by-one: индекс/граф хранят 0-based строки (340 вместо 341)

- **Источник:** AGENT_DIARY.md
- **Описание:** **verified_from_clean_state:** ✅ live — LanceDB после реиндекса+рестарта: save_symbol_index start_line=341, _ensure_symbol_index=332; runtime-status 🟢 9191 chunks; check_index.py подтвердил; pytest 15...
- **Статус:** автоматически синхронизировано


## 2026-08-28 — Env-extractor: deferred languages + from-import limitation (OPEN / STABLE)

**Что:** `extract_env_accesses` покрывает 14 расширений из 17 в MSCodeBase. Исключения: (1) `.swift`, `.dart`, `.sh`, `.bash` — грамматика есть, но в cbm-таблицах lang_specs.c нет записей; экстрактор возвращает `[]` (silent skip, не ошибка). (2) Языки cbm без грамматики в MSCodeBase: elixir, haskell, ocaml, r, perl, lua, zig, clojure, erlang — deferred. (3) Паттерн матчит только полное `os.environ[...]`/`process.env[...]`; форма `from os import environ` → `environ["X"]` НЕ даёт запись (cbm-семантика сохранена дословно, матч по полному pattern).
**Fix:** при необходимости добавить в `ENV_MEMBERS_BY_LANG` Python — `environ` (unqualified), JS — `env` (unqualified). Пока: KNOWN_LIMITATION.
**Статус:** 🟡 STABLE | **Deadline:** — | **Владелец:** misha.
**Note:** tree-sitter-node-типы `subscript_expression` (JS/TS) и `element_reference` (Ruby) добавлены как локальные расширения `_ENV_MEMBER_NODE_TYPES` — это терпимое усиление спеки (алгоритмический смысл «доступ к полю по индексу»), не нарушение. Java `System.getenv` не ловится — `method_invocation` нет в MSCodeBase `CALL_NODES` (preexisting limitation extract_calls, не введённая портом).
