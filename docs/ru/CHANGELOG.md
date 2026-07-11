<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](../en/CHANGELOG.md) • [🇷🇺 Русский](CHANGELOG.md) • [🇨🇳 中文](../zh/CHANGELOG.md)

# Журнал изменений

Все значимые изменения в этом проекте документируются в данном файле.

## [3.1.0] — 2026-07-11 — Улучшения на основе CodeGraph

### Добавлено
- 📊 **Адаптивный размер ответа**: `search_code` сам подбирает limit под размер проекта (<500 файлов→4, <5K→6, <15K→8, ≥15K→10). Явный `limit` всё ещё работает.
- 🕐 **Индикатор устаревания**: предупреждение "Index may be stale", если последняя индексация >1ч назад. Один лёгкий SQL-запрос, без сканирования диска.
- 🧩 **Графовый контекст в результатах**: `_expand_graph_context` выполняется для ВСЕХ режимов (был только `deep`). Каждый результат показывает кто его вызывает — прямо в ответе, без лишних вызовов.
- 🔇 **Фильтр DEFAULT_TOOLS**: по умолчанию видимы только 12 основных инструментов. Остальные 44 остаются в коде, включаются через `MSCODEBASE_MCP_TOOLS`. `MSCODEBASE_MCP_TOOLS=""` показывает все 56.
- 🏷️ **ToolAnnotations** (`readOnlyHint`): все read-only инструменты получили `readOnlyHint: true` — необходимо для Cursor Ask mode.
- 📁 **Единый extensions**: новый `src/core/extensions.py` заменяет 3 разошедшихся списка `SUPPORTED_EXTENSIONS`. Union всех трёх + разделение по назначению.
- 🛡️ **Защита схемы SQLite**: проверка существования `scoped_kv_store` при старте. Предупреждение в логах, не падение.
- 📋 **Лог версии MCP**: версия протокола логируется при старте для диагностики совместимости.
- 🔧 **Таймауты LSP в .env**: `LSP_REQUEST_TIMEOUT` и `LSP_START_TIMEOUT` вынесены в `.env.example`. `get_event_loop()` → `get_running_loop()` (Python 3.12+).
- 📈 **BENCHMARK.md**: реальные бенчмарки — 289ms fast mode, 8-18x экономия токенов, распределение latency по режимам.

### Изменено
- `search_code`: расширение графовым контекстом теперь для ВСЕХ режимов (был только deep)
- Видимость инструментов: 12/56 по умолчанию (раньше все 56)
- Приоритет LSP: basedpyright > pyright в `_find_server()`
- Таймаут: git-проверка в health report снижена 30→15s

### Исправлено
- `_show_all` в DEFAULT_TOOLS: `MSCODEBASE_MCP_TOOLS=""` теперь корректно показывает все инструменты
- Устаревший `asyncio.get_event_loop()` → `get_running_loop()` в LspClient

---

## [3.0.0] — 2026-07-11 — Write Tools + LSP Client + Meta-Patching

### Добавлено
- ✏️ **6 Write Tools**: `rename_symbol`, `move_symbol`, `safe_delete`, `replace_symbol`, `insert_before_symbol`, `insert_after_symbol` — все с preview/apply + декоратор `@modification_guard` (PageRank + blast radius + ack TTL)
- 🧠 **LspClient**: тонкий LSP-клиент для pyright (JSON-RPC 2.0 через stdio, ленивый запуск, авто-перезапуск, graceful fallback)
- ⚡ **P0 Meta-Patching**: `move_chunks_metadata` — обновление file_path в LanceDB БЕЗ пере-эмбеддинга (30-80ms против 2000-5000ms, 0MB RAM против 700MB)
- 🛡 **Modification Guard**: `@modification_guard(pagerank_min, blast_min, ack_ttl)` — предотвращает запись в критически важные файлы без явного подтверждения
- 🔄 **Расширения SymbolIndex**: `find_all_references()`, `rename_symbol()`, `has_symbol()`, `remap_file()`
- ⚡ **BM25 fast invalidation**: `_reset_bm25()` — сброс кэша вместо полной перестройки

### Исправлено
- `intelligence_layer.py` — `_resolve_symbol_count` на колонке 0 «проглатывал» все методы классов (Intel-инструменты были невидимы). Перемещён до определения класса
- `intel_get_runtime_status`, `intel_log_incident` и все Intel-инструменты теперь работают корректно (11 методов на ProjectIntelligenceLayer)

---

## [2.7.1] — 2026-07-11 — SQLite кэш, статус индекса, docs синхронизация

### Added
- 🔧 CRT API Set patcher для Windows Insider (build >= 26000) — патч PE-импортов api-ms-win-crt → ucrtbase
- 🖥️ Vulkan GPU поддержка — авто-детекция + `LLAMA_BACKEND=vulkan` + `-ngl 99`
- 🔄 `verify_index_freshness()` — проверка SHA256 хэшей (2-5 сек вместо 5 мин полной переиндексации)
- 💾 SQLite connection cache — `_get_sqlite_connection()` с TTL 2с (вместо 2 новых коннектов на вызов)
- 📝 `docs/KNOWN_ISSUES.md` — единый реестр P0-P3 проблем и техдолга

### Fixed
- `server.py:329-331` — SQL ORDER BY добавлен в `scoped_kv_store` (multi-window race)
- `indexer.py:get_status()` — `_cached_unique_files` fallback: если кэш пуст, а чанки есть — scan LanceDB
- `ui_formatter.py:193` — `symbols` читался из `total_files` вместо `symbol_index_count`
- `intelligence_layer.py` — добавлен `symbol_index_count` в index_telemetry
- `llama_runner.py` — `-ngl` ternary fix: `else "-ngl","0"` → `else "0"`
- `llama_runner.py` — дубликат ключа 'bge-m3' в GGUF_MODELS (восстановлен 'qwen3-embedding')
- `health_report.py` — read-only check (больше не удаляет orphans из индекса)
- `install.py` — `llama_msvc`, `llama_vulkan`, `models` добавлены в skip-лист
- RRF pseudo-code в `SEARCH_PIPELINE.md` — исправлен `enumerate(bm25 + dense)` на раздельные enumerate

### Docs
- 28 файлов синхронизировано (12 en + 6 ru + 9 zh + 1 код)
- `AI_INSTALLATION_PROMPT.md` — переписан под real workflow (install.py → test MCP → reload)
- `README.md` (en/ru/zh) — очищены от бутафории: 43→50 tools, LM Studio→llama.cpp primary
- `CHANGELOG.md` — исправлены битые ссылки на LSP_WONTFIX.md
- `HANDFOFF.md` — 34→33 core tools

---

## [2.7.0] — 2026-07-09

### Added
- 🦙 llama.cpp как основной провайдер (авто-установка через install.py)
- LlamaRunner — менеджер lifecycle для llama-server.exe (скачивание, запуск, остановка)
- GGUF модели: bge-m3 Q4_K_M (417 MB) + bge-reranker-v2-m3 Q4_K_M (418 MB)
- Платформенная детекция: Windows/macOS/Linux, x64/ARM64
- `docs/research/2026-07-09-provider-benchmark.md` — полный бенчмарк

### Changed
- installer: 10→12 шагов (+llama.cpp, +GGUF моделей)
- `patch_zed_settings`: сохраняет // комментарии, no-op guard
- Приоритет провайдеров: LM Studio → llama.cpp → ONNX server → local ONNX
- MCP: 227 MB RAM (было 1200 MB) — в 5.3x меньше
- ONNX server: `Tokenizer.from_file()` вместо `AutoTokenizer` — без зависаний

### Fixed
- `AutoTokenizer.from_pretrained()` зависание на Windows (HTTP к huggingface.co)
- `patch_zed_settings` вырезал // комментарии → кнопка "восстановить"
- `_detect_model_dir()` создавал 544 MB InferenceSession только для чтения размерности
- Все HTTP-клиенты: `httpx.Limits(keepalive_expiry=30.0)` для Zed 1.10.0 compat

---

## [v2.5.3] — 2026-07-07 — mode=ask: RAG-генерация ответа через phi-4

### 🚀 mode=ask
- **`src/core/searcher.py`**: Новый метод `Searcher.ask_async()` — гибридный поиск → контекст → phi-4 (chat completion) → структурированный ответ с цитатами.
- **`src/mcp/tools/search_tools.py`**: Добавлен режим `mode="ask"` с защитой: в `light` profile — автоматический fallback на `quality` с предупреждением.
- **`src/core/config.py`**: `ASK_TIMEOUT` (60s), `ASK_MODEL` (phi-4-mini-instruct).

### 📦 Версии
- `extension.toml`: 2.5.2 → 2.5.3
- `src/__init__.py`: 2.5.2 → 2.5.3

---

## [v2.5.2] — 2026-07-07 — phi-4-mini-instruct verified + live test

### 🔬 LM Studio
- `phi-4-mini-instruct Q4_K_M` протестирована через `/v1/chat/completions`: успешный ответ (75 токенов, `finish_reason=stop`).
- Модель загружается on-demand (state: not-loaded → auto-load).
- Подтверждена готовность к `mode=ask` (v2.7.0).

### 📦 Версии
- `extension.toml`: 2.5.1 → 2.5.2
- `src/__init__.py`: 2.5.1 → 2.5.2

---

## [v2.5.1] — 2026-07-07 — Multi-Bucket RAG + Contextual Retrieval + Profiles

### 🚀 Multi-Bucket RAG (Phase 1)
- **`src/core/searcher.py`**: Overfetch (`raw_limit = min(limit * factor, MAX)`), распределение по bucket'ам на основе `CODE_EXTENSIONS`/`DOCS_EXTENSIONS`, soft weighting ДО reranker, cut-to-limit.
- **`src/core/config.py`**: `CODE_EXTENSIONS`, `DOCS_EXTENSIONS`, `MAX_RERANKER_INPUT=30`, `overfetch_factor`, `code_bucket_weight`, `docs_bucket_weight` — все через `.env`.

### 🧩 Contextual Retrieval (Phase 2)
- **`src/core/parser.py`**: Новый формат префикса для кода: `// File: {path} | Context: {class}.{func}`, для .md: `From {path}, section '{heading}':`. Требуется переиндексация.

### ⚖️ Soft Scoring + intent_hint (Phase 3)
- **`src/mcp/tools/search_tools.py`**: Новый параметр `intent_hint` (`"auto"` / `"code"` / `"docs"`).
- **`src/core/searcher.py`**: `_apply_bucket_weights()` — динамические веса: code=1.2/docs=0.8 для `"code"`, code=0.8/docs=1.2 для `"docs"`, 1.0/1.0 для `"auto"`.

### ⚙️ SYSTEM_PROFILE (Phase 4)
- **`src/core/config.py`**: `SYSTEM_PROFILE=light|server` с валидацией и свойствами `is_light_profile`/`is_server_profile`. `light` — синхронный режим (по умолч.), `server` — зарезервирован.

### 📦 Версии
- `extension.toml`: 2.4.4 → 2.5.1
- `src/__init__.py`: 1.0.0 → 2.5.1

---

## [v2.4.7] — 2026-07-05 — LM Studio Connection Pool + Warm-up

### ⚡ Производительность
- **`src/core/remote_embedder.py`**: Добавлен `httpx.AsyncClient` с **connection pool** (5 keepalive-соединений, 60s expiry) — убирает TCP/TLS overhead на каждый embed-запрос.
- **`src/core/remote_embedder.py`**: Новый метод `embed_batch_async()` — async embed через единый HTTP-клиент. `searcher.py` автоматически подхватывает его.
- **`src/mcp/server.py`**: `_warmup_embedder()` при старте сервера — прогревает bge-m3 тестовым запросом, убивая cold start ~3s у первого search_code.

---

## [v2.4.6] — 2026-07-05 — UI Formatter + Deadlock Fix + Log Centralization

### 🐛 Исправление дедлока
- **`src/core/rate_limiter.py`**: `DebounceBatch._debounce_wait()` больше не вызывает `await` внутри `threading.Lock` — вынесено в отдельную переменную `should_flush`. `threading.Lock` не reentrant — дедлок 100% при пачке `notify_change`. Исправлены code quality: удалён `field`, добавлен `Any`.

### 🎨 UI Formatter (новый модуль)
- **`src/utils/ui_formatter.py`**: 8 базовых функций форматирования: `header()`, `table()`, `key_value()`, `code_block()`, `empty_result()`, `error_result()`, `ok_result()`, `format_search_code()`, `format_repo_rank()`, `format_health_report()`, `format_telemetry()`, `format_eta()`.
- Все данные под `<details>`-спойлер, Markdown-таблицы вместо JSON.

### 🔄 Централизация логов
- **`src/core/log_manager.py`**: `get_log_dir()` теперь ВСЕГДА ведёт в `ext_root/.codebase_indices/logs/`, а НЕ per-project. Добавлена `_cleanup_stale_project_logs()` — чистит старые логи из проектов.
- Очищены импорты: удалены `datetime`, `timedelta`, `timezone`, дубль `import os`.

### 🧩 Интеграция UI Formatter
- **`src/mcp/tools/search_tools.py`**: `_format_results()` переведён на `format_search_code()`. Вывод — таблица с колонками #, Файл, Строка, Фрагмент, Слой.
- **`src/mcp/tools/system_tools.py`**: `GetIndexStatusTool.execute()` — вывод через `header() + key_value() + code_block()`.
- **`src/mcp/tools/analysis_tools.py`**: `GetRepoRankTool.execute()` — вывод через `format_repo_rank()` с таблицей и сырыми JSON под спойлером.

### 🧠 Проектная память
- `known_issues`: LSP WONTFIX на Zed 1.9.0 Windows (NODE-567a10)
- `incidents`: INC-2CE4, INC-8817

---

### 📄 Документация
- **Новый отчёт-расследование**: [`LSP_WONTFIX.md`](investigations/LSP_WONTFIX.md). Полный аудит исходников Zed 1.9.0 (`crates/project/src/lsp_store.rs`, `crates/extension/src/extension_manifest.rs`, `crates/settings_content/src/language.rs`) с цитатами кода и ссылками на raw GitHub. Вердикт: **WONTFIX на Zed 1.9.0** — кастомный LSP нельзя зарегистрировать только через `settings.json`, нужен Rust+WASM-обёртка.

### 🧹 Очистка мёртвого кода
- **`install.py`**: удалена генерация LSP-конфига (`lsp_config`). LSP-секция в `settings.json` больше не создаётся — она не работает (WONTFIX).
- **`src/utils/zed_config.py`**: удалён блок регистрации `lsp.mscodebase-lsp` из `patch_zed_settings()`. Функция больше не принимает LSP-конфиг.
- **`scripts/check_lsp_health.py`**: новый диагностический скрипт. Проверяет settings.json, процессы, bridge-файлы, SQLite DB. Выдаёт понятный вердикт с рекомендациями.

### 📚 Документация
- **`ZED_WINDOWS_QUIRKS.md`** (1.0 → 1.1): новая секция «LSP не стартует в Zed 1.9.0 (WONTFIX)» с реальной первопричиной.
- **Обновлён** `AGENT_DIARY.md`: новая запись 15:55 с правильным root cause и ссылкой на отчёт-расследование. Старая запись 15:30 помечена DEPRECATED.

### 🧠 Проектная память
- В `known_issues` добавлен узел про LSP-WONTFIX с ссылкой на отчёт и тремя workaround'ами (MCP, SQLite fallback, подмена pyright).

### ℹ️ Что это меняет
- **MCP остаётся основным транспортом** для всех сценариев код-ассистента.
- **LSP-фичи в редакторе (inlay-hints, code-actions, автокомплит)** на Zed 1.9.0 Windows невозможны без Rust-обёртки — by design, не наш баг.
- **Для v3.0** запланирован путь A (Rust+WASM-обёртка через `impl zed::Extension::language_server_command`).

---

## [v2.4.4] — 2026-07-05 — Metadata Enrichment: Semantic Compass + Flat Tree

### 🧭 Semantic Compass (MCompassRAG-style, src/core/parser.py + src/core/indexer.py)
- Каждый чанк теперь содержит `layer` (архитектурный слой: core/mcp/utils/tests/...).
- Авто-детекция слоя по пути файла без ручной разметки.
- Поле `module_name` — логическое имя модуля (core.parser, mcp.server).
- Поле `is_public` — публичный/приватный символ (по `_` префиксу).
- Поле `symbol_type` — AST-тип узла (function_definition, method_definition, ...).

### 🌳 Flat Tree (SproutRAG-style, src/core/parser.py + src/core/indexer.py)
- `hierarchy_level`: function | method | class | impl | lines | function_part | section.
- `parent_id`: детерминированный md5-хеш родительского элемента.
  - Для метода: хеш `file_path::ClassName`.
  - Для функции: хеш `file_path` (модуль).
  - Multi-granularity retrieval без графовых БД.

### 🗃 Схема LanceDB
- 6 новых полей: `layer`, `module_name`, `hierarchy_level`, `is_public`, `symbol_type`, `parent_id`.
- Автомиграция через `_migrate_add_metadata_columns()` — без drop_table.
- Старые чанки получают пустые значения; заполнятся при переиндексации.

### 🔧 Код
- `src/core/parser.py`: +`_build_chunk_metadata()` — 4 точки создания чанков.
- `src/core/indexer.py`: +`_migrate_add_metadata_columns()`, +`chunk_metadatas`.
- Все 103 теста пройдены, ни один не сломан.

### 🎯 Фильтрация поиска по layer (MCompassRAG — поиск)
- `search_code` получил параметр `filter_layer` (core/mcp/utils/tests/...).
- LanceDB `.where()` с `prefilter=True` — фильтр на уровне индекса, без загрузки всех чанков.
- BM25 пост-фильтрация по layer из metadata.
- Работает во всех режимах: fast (vector-only), quality (hybrid), deep.

### 🌳 Multi-granularity retrieval (SproutRAG — поиск)
- Новый метод `Searcher.get_chunks_by_parent_id()` — находит все дочерние чанки по parent_id.
- Позволяет подняться по иерархии: модуль → класс → функция.
- E2E: фильтр core выдаёт только core, фильтр tests — только tests, 0 пересечений.

---

## [v2.4.3] — 2026-07-05 — RuntimeCoordinator + intel_get_project_context

### 🎯 RuntimeCoordinator (новый, src/core/runtime_coordinator.py)
- Единая точка принятия решения "можно ли выполнять MCP-запрос?".
- Использует Registry (состояние), SystemArtifacts (системный путь), Runtime Passport (готовность).
- `can_execute(path) → ExecutionVerdict(ok, reason, state, detail)`.
- `require_ready_project()` в MCPTool делегирует Coordinator-у.
- Имя tool: `intel_get_project_context` (единый стиль Intel Layer).

### 🧪 Код
- ProjectContext, RuntimeCoordinator, server.py, base.py — синтаксис OK.
- Архитектура: Tool → Coordinator → Snapshot, без копипасты.

---

## [v2.4.2] — 2026-07-05 — ProjectContext — единая модель состояния проекта

### 🏗 ProjectContext (новый, src/core/project_context.py)
- Единый объект-снэпшот проекта: state + index + bridge + health + memory + jobs.
- Вместо 5 разных вызовов — один `await ctx.capture()`.
- Все поля опциональны: если компонент недоступен → None, без падения.
- `get_project_context` MCP tool — JSON со всей картиной проекта сразу.
- Ничего не ломает — новый слой поверх существующей архитектуры.

### 🔧 SystemArtifacts (src/core/system_artifacts.py)
- Единый модуль для идентификации системных файлов (4 уровня защиты).
- file_guard.py переведён на SystemArtifacts — все списки в одном месте.

---

## [v2.4.1] — 2026-07-05 — Extended Passport + Feedback-Loop Guard + Two-Stage Ready

### 🆔 Passport Extended (BUILD_ID + Bridge/Registry/ProjectState)
- **`src/mcp/server.py`**: добавлен `_BUILD_ID` (git commit hash) — мгновенная верификация версии кода.
- `_log_run_passport()` теперь логирует Bridge state и Registry state при старте.
- `debug_runtime_passport` возвращает: `build_id`, `project_state` (enum), `bridge`, `bridge_error`, `registry.paths`, `registry.cached_projects`, `registry.cache_hits/misses`.

### 🛡 Feedback-Loop Guard (против загрязнения индекса)
- **`src/core/file_guard.py`**: в `_load_gitignore()` добавлены явные паттерны исключения служебных файлов индексации:
  - `chunk_summaries.json`, `summaries_cache/**` — описания чанков
  - `incidents.json`, `project_memory.json`, `commits.json` — метаданные памяти
  - `.index_guard.json`, `symbol_index/**` — индексы
- Защита двухслойная: SKIP_DIRS (директории) + .gitignore (файлы).
- Без этих исключений возможен feedback loop: описание чанка → summary → индексирование summary → новое summary на основе предыдущего.

### ⏱ Two-Stage wait_until_ready
- **`src/mcp/tools/base.py`**: `require_ready_project()` теперь делает 2 стадии:
  1. Быстрая проверка bridge (1с) — если LSP ещё не записал project_root, сразу логирует предупреждение вместо ожидания 5с.
  2. Полное ожидание READY (оставшиеся секунды).

### 🧪 Tests
- Все файлы проходят py_compile.
- Индекс: 1362 чанка, 106 файлов, 1080 Tree-sitter символов, status=active.

---

## [v2.4.0] — 2026-07-05 — Self-Indexing Fix + Process Passport + Project State Machine

### 🛡 Self-Indexing Guard: Dev-Repo Fix
- **`src/mcp/server.py`**: удалён ошибочный `_SELF_INDEX_MARKER`
  (`(path / "src/lsp_main.py").exists()`), заменён на
  `_reject_self_index_target(p, source=)`.
  - Отклоняет: `p == _ext_root` + `is_zed_install_dir(p)`.
  - Больше НЕ блокирует dev-репозиторий (`D:\Project\MSCodeBase`), если
    пользователь открыл исходники расширения как проект в Zed.
- **`src/mcp/tools/base.py`**: добавлен env-override `MSCODEBASE_ALLOW_SELF_INDEX=1`
  для dev-сценария.
- **`src/utils/zed_config.py`**: `patch_zed_settings()` пишет
  `MSCODEBASE_ALLOW_SELF_INDEX=1` в env MCP/LSP.

### 🆔 Process Passport (debug_runtime_passport)
- **`src/mcp/server.py`**: при старте MCP логируется "паспорт" —
  `RUN_ID`, `PID`, `_ext_root`, `PROJECT_PATH`, `ZED_WORKTREE_ROOT`,
  `MSCODEBASE_ALLOW_SELF_INDEX`, `PYTHONPATH`.
- Зарегистрирован MCP-tool `debug_runtime_passport` — возвращает JSON
  с RUN_ID, PID, uptime, source_file, ext_root, env, guard result.
  Позволяет за 1 вызов подтвердить: "тот ли процесс исполняет мой код?".

### 🏗 Project State Machine (race-free multi-window)
- **`src/core/project_indexer_registry.py`**:
  - Добавлен `enum ProjectState`: `UNINITIALIZED → STARTING → INDEXING → READY → FAILED`.
  - Per-project `asyncio.Event` для сигнализации готовности.
  - `get_indexer()` автоматически переводит проект в STARTING при создании
    и в READY/INDEXING после.
  - `wait_until_ready(path, timeout=5.0)` — ожидает READY (решает race
    condition при переключении окон: LSP нового проекта ещё не записал
    bridge, но MCP уже получил tool call).
  - Исправлен дублированный `with self._create_lock` (удалена мёртвая копия).
- **`src/mcp/tools/base.py`**: добавлен `async require_ready_project()`
  в `MCPTool`. Инструменты ждут готовности вместо "последний активный проект".

### 🛠 Утилиты
- **`scripts/sync_src.py`** (new) — быстрая синхронизация `src/` из
  dev-репозитория в install-директорию расширения.
- **`scripts/patch_zed_settings.py`** (new) — патч глобального
  `settings.json` Zed для добавления `MSCODEBASE_ALLOW_SELF_INDEX=1`.

### 🧪 Tests
- Прямой запуск: `_is_self_index_path(D:\Project\MSCodeBase) = False`.
- `resolve_project_root()` возвращает `D:\Project\MSCodeBase` без ошибок.
- MCP-сервер стартует и регистрирует 43 инструмента (33+10).
- Индекс: 1362 чанка, 106 файлов, 1080 Tree-sitter символов, статус active.

---

## [v2.3.3] — 2026-07-05 — Visible Project Path + Self-Indexing Guard

### 🎯 Видимость пути проекта (INC-6BCB-v3)
Пользователь больше не должен гадать "где MCP ищет?". Теперь:

- **`search_code`** output начинается с `📂 Project: <path>`.
- **`index_project_dir`** output содержит `📂 Project: <path>` в финале.
- **`notify_change`** output содержит `📂 Project: <path>` после обновления.
- **`get_index_status`** output начинается с `📂 Project: <path>`.
- **`index_health`** output содержит `project_path`, `db_path`,
  `total_chunks` в JSON-ответе.

### 🛡 Жёсткий Self-Indexing Guard (ToolError, не молчаливый)
- **`resolve_indexer_for_request()`** (в `src/mcp/tools/base.py`) бросает
  `ToolError` если resolved project_path это:
  - `_ext_root` (исходники самого расширения)
  - Zed install dir (`is_zed_install_dir()`)
  - `None` (неопределённый project_root)
- **`IndexProjectDirTool`** делает **дополнительную** проверку ДО создания
  Indexer с понятным сообщением: "Refusing to index Zed install dir: ...".
- **Error detail** содержит инструкцию как починить (открыть проект явно,
  передать explicit project_root, или установить PROJECT_PATH env).

### 🐛 Исправление бага
- **`is_zed_install_dir()`** не находил `D:\AI\Zed` (корень установки)
  потому что маркеры требовали trailing path separator. Добавлены
  маркеры для root-of-install + нормализация backslashes/forward slashes
  для кросс-платформенного сравнения.

### 🧪 Tests
- **`tests/test_project_header.py` (new, 16 tests)**:
  - `_is_self_index_path()`: 7 кейсов (None, Zed install, ext_root, user project).
  - `resolve_indexer_for_request()`: 4 кейса (user OK, Zed install blocked,
    None blocked, ext_root blocked).
  - `_project_header()` / `_project_metadata()`: 5 кейсов (success, error,
    dict contents).
- **All tests pass: 323 / 323** (307 предыдущих + 16 новых).

### 📊 Smoke-тест
- `create_mcp_server()` стартует за 8.61s, 33 tools + 4 handlers.
- `indexer.bm25_batch` per-project (v2.3.1) + project header (v2.3.3)
  работают вместе.

---

## [v2.3.2] — 2026-07-05 — Multi-Root Awareness + Self-Indexing Guard

### 🐛 Критический баг: Self-Indexing Zed Install Dir
- **Симптом:** MCP индексирует `D:\AI\Zed\` (саму установку Zed) вместо
  пользовательского проекта. Видно как `db_isolated_path:
  D:\AI\Zed\.codebase_indices\...` в `intel_get_runtime_status`.
- **Корень:** LSP получает от Zed `params.root_uri` (или `workspaceFolders`).
  Если Zed открыт с `D:\AI\Zed` как worktree root (последний открытый
  workspace, или Zed IDE запущен без явного проекта), LSP пишет в bridge
  именно этот путь, и MCP индексирует всю директорию Zed (exe, dll, конфиги).
- **Решение:**
  1. `lsp_project_bridge.is_zed_install_dir(path)` — детектит Zed install dir
     по маркерам в пути (Zed.exe, %LOCALAPPDATA%\Zed, и т.п.) и по
     наличию Zed.exe рядом с директорией.
  2. `lsp_main.on_initialize` — читает `params.workspaceFolders` (LSP 3.6+),
     фильтрует Zed install dir, инициализирует DI для каждого оставшегося.
  3. `lsp_project_bridge.write_active_project` — принимает `all_workspaces`
     список URI всех воркспейсов.
  4. `lsp_project_bridge.read_active_project` — выбирает первый non-Zed-install
     workspace из `all_workspaces`, fallback на `project_root`.
  5. LSP-сервер теперь объявляет `workspace.workspaceFolders` capability
     (supported: True, changeNotifications: True) — Zed будет присылать
     `workspace/didChangeWorkspaceFolders` при открытии/закрытии проектов.

### 🔧 Multi-Root LSP
- `ls._all_workspaces` — список URI всех открытых воркспейсов (для watcher'ов).
- Per-workspace DI: для каждого folder из `workspaceFolders` создаётся
  свой `_services_per_workspace[uri]`. Если Zed откроет 3 проекта —
  будет 3 DI-контейнера, 3 ProjectIndexerRegistry, 3 .codebase_indices/.

### 🧪 Тестирование: 306 passed + 1 pre-existing failure
- Все предыдущие тесты прошли без изменений.
- `test_expected_message_mismatch` — pre-existing, не связан с v2.3.2.

### 📚 Миграция
- После обновления: `sync_to_installed.bat --full` + перезапуск Zed.
- Если `D:\AI\Zed\.codebase_indices/` содержит мусор от self-indexing —
  можно удалить вручную: `rm -rf /d/AI/Zed/.codebase_indices`.
- Чтобы Zed точно открыл проект: `cmd+shift+p` → "Open Project" →
  выбрать `D:\Project\MSCodeBase` (создаст `.zed/` workspace marker).

---

## [v2.3.1] — 2026-07-05 — Startup Hang Fix + DebounceBatch Per-Project

### 🐛 Исправления критических багов
- **`lsp_main.py:did_change_watched_files`** — `if _services is None` бросал `NameError` (глобальная `_services` не существует в per-workspace архитектуре). Заменено на lookup в `_services_per_workspace[uri]` с fallback на первый доступный. Без этого watcher-events падали с NameError при первом же срабатывании.
- **`lsp_main.py:did_change`/`did_close`/`did_save`** — workspace_uri и project_root НЕ передавались в `_execute_file_indexing` (только `did_open` передавал). В multi-window это значит, что все индексируемые файлы попадали в default Indexer. **Исправлено** — все четыре хука теперь пробрасывают `getattr(ls, "_workspace_uri", "")` и `getattr(ls, "_project_root", None)`.
- **`lsp_main.py:_execute_file_indexing`** — `services.resolve(type("_IndexerFactory", (), {})) if False else ...` (мёртвый код с анонимным type) заменён на прямой `_get_factory(services)`. Аналогично `services.resolve(type("ProjectRootKey", (), {}))` → `services.resolve(ProjectRootKey)`.
- **`search_tools.py:_agentic_search`** — `self.searcher` и `self.symbol_index` НЕ существуют в базовом `MCPTool` (Indexer/Searcher per-project через registry). Заменено на `self.resolve_searcher()` / `self.resolve_symbol_index()`. Без этого agentic_search падал с AttributeError.
- **`graph_tools.py:GraphQueryTool`** — `services.resolve(SymbolIndex)` + `services.resolve(Indexer)` в `__init__` (Indexer больше не singleton) заменены на `self.resolve_symbol_index()` / `self.resolve_indexer()` per-call. Fallback `Path.cwd()` для project_root убран.
- **`mcp/server.py:IntelligenceLayer`** — `services.resolve(Indexer/Searcher/SymbolIndex)` (все три не зарегистрированы) заменены на `resolve_indexer_for_request(services)`. Без фикса 10 intel_* tools не регистрировались (warning "Intel layer not registered").
- **`mcap/server.py:33+13` → `33+10`** — корректный счёт (10 intel tools, а не 13).

### 🔧 Per-Project DebounceBatch (multi-window)
- **Раньше:** `DebounceBatch` регистрировался в DI как singleton с захватом default `ProjectRootKey` — для не-default проектов BM25 reindex работал с **неправильным** project_root (все per-project файлы реиндексировались default Searcher-ом).
- **Теперь:** `bm25_batch` создаётся per-project внутри `_create_indexer_for_path()` (захватывает конкретный `Indexer` в closure) и хранится как `indexer.bm25_batch`. Все потребители (`lsp_main.py:_execute_file_indexing`, `lsp_main.py:_process_watched_changes`, `mcp/tools/indexing_tools.py:NotifyChangeTool`) берут batch из `indexer.bm25_batch` через `getattr(indexer, "bm25_batch", None)` с fallback на синхронный `searcher.reindex()`.
- **`di_container.py`** — `_batch_reindex_bm25_factory` и `services._factories[DebounceBatch]` удалены. `_create_indexer_for_path` теперь явно создаёт `p_indexer.bm25_batch = DebounceBatch(callback=..., config=...)`.
- **Late-binding fix:** `_create_indexer_for_path` объявлен ПОСЛЕ `notification_broker` (раньше использовал late-binding через globals — хрупко). Захват переменных через default args (`_embedder=embedder, _notification_broker=notification_broker`) делает поведение детерминированным.

### 🚀 Self-Indexing Guard + Bridge Recheck
- **`_trigger_auto_index_if_empty`** — добавлена проверка `indexer.project_path == _ext_root`. Если resolve_project_root упал в fallback (race с LSP), auto-index **не запускается** (раньше индексировал ~500MB исходников самого расширения).
- **Delayed bridge recheck** — фоновая задача через 1.5s после старта MCP повторно читает `read_project_from_bridge(max_wait=2.0)`. Если LSP успел записать project_root — `reset_project_root_cache()` сбрасывает кэш, и последующие вызовы `resolve_project_root` выберут bridge. **Решает race LSP↔MCP** при cold start.

### 🧹 Housekeeping
- **`mcp/tools/base.py`** — удалён мёртвый код `_indexer_factory_from_services` и `_IndexerFactoryKey` (не используется с v2.3.0).
- **`mcp/tools/indexing_tools.py`** — удалён неиспользуемый импорт `DebounceBatch`.
- **`mcp/tools/graph_tools.py`** — удалён неиспользуемый импорт `SymbolIndex`.

### 🧪 Тестирование: 307 passed
- `tests/test_di_container.py::test_creates_all_services` — убран `DebounceBatch` из списка (больше не singleton).
- `tests/test_di_container.py::test_debounce_batch_uses_searcher` — переписан: batch берётся из `indexer.bm25_batch`, а не через `services.resolve(DebounceBatch)`.
- Все остальные 305 тестов прошли без изменений.

### 📚 Заметки по миграции
---

## [v2.3.0] — 2026-07-05 — Multi-Window Support & Hardening

### 🏗️ Архитектура: Multi-Window
- **`ProjectIndexerRegistry`** (new, `src/core/project_indexer_registry.py`):
  Per-project `Indexer` с lazy созданием и LRU eviction (5 слотов).
  Каждое открытое окно Zed получает изолированный `Indexer`/
  `FileGuard`/`SymbolIndex`/`db_path` — переключение окон больше не ломает state.
- **`ResourceMonitor`** (new, `src/core/resource_monitor.py`):
  stdlib-only мониторинг RAM/CPU (`resource.getrusage` + `ctypes/psapi` на Windows,
  без `psutil`). Soft/hard пороги для adaptive throttling.
- **LSP per-workspace DI**: `_services_per_workspace[uri]` вместо одного
  глобального `_services`. `init_components(project_root, workspace_uri=...)`.
- **MCP `resolve_indexer_for_request`**: per-project indexer из registry
  с приоритетом: explicit kwarg → `resolve_project_root()` → DI default.

### 🔧 Hardening
- **`_safe_close()`**: обнуляет LanceDB connection + кэши + `gc.collect()` —
  освобождает `.lance` mmap handles на Windows немедленно.
- **Adaptive throttling**: `Indexer.index_project` замедляется при soft
  pressure (0.1s) и останавливается при hard pressure (до 2s).
- **HealthReport `_check_resources`**: rss_mb, cpu_percent, threads,
  registry stats (cached/evictions/hits/misses) в `metrics`.
- **`async indexer` reentrancy**: `_indexing_serial_lock` в LSP сериализует
  запись в LanceDB между `did_open`/`did_change`/`did_save`.

### 🐛 Исправления багов (аудит INC-53EC, 19 issues)
- `di_container.py:177` — `notification_broker` NameError в `CircuitBreaker.on_state_change`
- `lsp_main.py:372` — undefined `_indexer` global в `did_change_watched_files`
- `did_change` debounce 350ms (не на каждый keystroke)
- `asyncio.Lock` → `threading.Lock` (cross-loop safe: LSP pygls loop + MCP asyncio.run loop)
- Sentinel DI keys (`ProjectRootKey`/`DbPathKey`/`IndexerFactoryKey`) вместо `str`/`type("…")`
- `indexer.set_searcher(searcher)` вместо `indexer.searcher = …` (encapsulation)
- `SafePathManager.cleanup` через `atexit` + `weakref.finalize`
- `add_columns` миграция LanceDB вместо `drop+create` race
- `O(N) to_pandas()` заменён на `table.search().where(...).limit(1)`
- LSP watcher glob `**/*.{ext1,ext2,…}` (фильтр по расширениям)
- `git log` с `cwd=project_path` в HealthReport
- `HeartbeatService` class (DI-friendly) вместо module globals
- `IndexGuard` reconciliation (prior `needs_reindex` не залипает)
- `nul` файл удалён (Windows reserved name)

### 🔧 Настройки Zed
- `current_dir` убран из `patch_zed_settings` (Zed не подставляет
  `$ZED_WORKTREE_ROOT` в `current_dir` — bug #36019). `resolve_project_root`
  обрабатывает приоритеты сам: PROJECT_PATH env → bridge → CWD → ext_root.
- `fix_zed_settings.bat` (new) — патчит существующий `settings.json` пользователя
  (удаляет `current_dir` с бэкапом).
- Self-indexing guard: PROJECT_PATH указывает на MSCodeBase → warning в логах.

### 🧪 Тестирование: 325 → 307 passing (+ 11 new = 318; 11 deprecated, минус = 307)
- `test_resource_monitor.py` (new, 11 tests):
  - `ResourceMonitor`: sample, throttle, pressure thresholds, summary, singleton
  - `ProjectIndexerRegistry`: singleton per path, LRU eviction, pressure eviction,
    explicit evict, stats (hits/misses/evictions)
- `test_health_report.py`: degraded status, total_symbols/embedder_mode алиасы,
  orphan-files detection, git log cwd, fallback embedder warning
- `test_integration.py`: `isolated_indexer` использует `temp_project` как
  `project_path` (был баг — FileGuard отвергал файлы как "not in project")
- `test_di_container.py`: `Indexer`/`Searcher` теперь per-project через registry

### 📚 Документация
- README: tests badge 325 → 307, добавлен Multi-Window в features
- `docs/architecture.md`: секция "Multi-Window Registry" + ResourceMonitor
- CHANGELOG: этот файл
- `pyproject.toml`: bumped to v2.3.0
- AGENT_DIARY.md: 3 записи (аудит + multi-window + resource monitor)

### ⚠️ Заметки по миграции
- После обновления запустите `fix_zed_settings.bat` для удаления
  `current_dir` из `~/.config/Zed/settings.json` (или `%APPDATA%\Zed\settings.json`).
- `sync_to_installed.bat --full` для синхронизации с установленной копией.
- Перезапустите Zed для подхвата новых версий.

---

## [v2.2.0] — 2026-07-04 — Architecture Modernization

### 🏗 Переписывание архитектуры
- **DI Container:** `ServiceCollection` с Constructor Injection (15 services)
- **server.py:** 3,100 → **220 строк** (-93%). God Object устранён.
- **37 инструментов** разделены на 10 предметных файлов в `src/mcp/tools/`
- **error_boundary** decorator: унифицированные JSON-ответы, реальный `asyncio.wait_for` timeout
- **DebounceBatch:** BM25 реиндексация через 500ms debounce (не на каждый файл)
- **SlidingWindowRateLimiter:** защита от VFS-петель (10 req/sec max)
- **CircuitBreaker:** CLOSED/OPEN/HALF_OPEN для LM Studio (5 failures → 30s recovery)
- **hybrid_server.py:** DEPRECATED (вся логика в DI Container + lsp_main.py)

### 🔧 Улучшения
- `lsp_main.py` — 4 глобальные переменные → DI container (`_services`)
- `notify_change` — Rate Limiter + DebounceBatch вместо немедленной BM25
- `get_index_progress` — progress tracking как module-level exports
- `read_live_file` — новый инструмент (чтение из LSP VFS с disk fallback)
- `_resolve_project_path` → standalone `resolve_project_root()`
- `GIT_ASKPASS=echo` + `CREATE_NO_WINDOW` — защита от Git Hang на Windows
- `_is_complex_query` — исправлена: русская грамматика → token-based + English W-words

### 🧪 Тестирование
- 52 новых unit-теста для:
  - `error_handler.py` — ToolError, error_boundary (async + sync), timeout, retries
  - `rate_limiter.py` — SlidingWindow, DebounceBatch, CircuitBreaker (all states)
  - `di_container.py` — ServiceCollection, 15 DI services, Searcher↔Indexer cycle
- Всего: **325 тестов**

### 📚 Документация
- README полностью переписан: 37 инструментов, Clean Architecture с DI
- `docs/ARCHITECTURE.md` — новая схема с DI Container + tool files
- CONTRIBUTING.md — обновлён под новый архитектурный стиль
- AGENT_DIARY.md — 5 записей (все фазы рефакторинга)
- pyproject.toml: bumped to v2.2.0

---

## [v2.1.0] — 2026-07-03

### 🚀 Major
- **Консолидация поиска:** `search_code(query, mode)` — единый инструмент с 5 режимами (`auto/fast/quality/deep/context`)
- **Intelligence Layer:** 10 высокоуровневых `intel_*` инструментов (самодиагностика, топология, память проекта)
- **Отказ от double-write:** `patch_zed_settings()` теперь single-pass (MCP + LSP + Languages за один вызов)
- **Проектная память:** ADR, known_issues, tech_debt, failed_attempts — автоматически сохраняются между сессиями

### 🔧 Улучшения
- `get_health_report`/`index_health` — `project_root` опционален (fallback на `$PROJECT_PATH`)
- `notify_change` — правильный резолв путей от корня проекта (не CWD)
- `_resolve_project_path()` — централизованный helper для резолва корня проекта
- Централизованная обработка путей через `PROJECT_PATH` env var (устанавливается Zed)
- `install.py` — clean-up: удалён дублирующий код LSP (теперь в `patch_zed_settings`)

### 📚 Документация
- README полностью переписан: 26 инструментов, search_code с mode, Intel Layer
- `docs/architecture.md` — обновлён список инструментов (14→26 + 10 intel_*)
- `docs/windows-setup.md` — обновлён под новый формат
- `CONTRIBUTING.md` — убраны упоминания deprecated инструментов
- Создан `sync_to_installed.bat` для быстрой синхронизации source→installed

### 🧹 Housekeeping
- Удалены `run_tests.py`, `run_tests.bat` (дубликаты `pytest`)
- Обновлён `.gitignore` (добавлены dev-артефакты)
- Корень проекта очищен от тестового мусора

### ⚠️ Deprecations
- `smart_search`, `deep_search`, `context_search` → используйте `search_code(query, mode=...)`
- Старые функции пока работают как обёртки (backward compatibility)

## [v2.0.0] — 2026-06-28

### 🚀 Major
- Гибридная архитектура LSP + MCP: единый процесс с общей памятью вместо отдельных серверов
- Полный отказ от межпроцессного взаимодействия — снижение задержек и упрощение деплоя

### ⚠️ Breaking Changes
- Требуется миграция с предыдущей архитектуры на единый LSP+MCP процесс
- Изменены точки интеграции с редактором (больше нет отдельного MCP-сервера)
- Обновлён формат конфигурации

## [v1.4.2] — 2026-06-28

### 🔧 Улучшения
- Миграция с ThreadPoolExecutor на asyncio.gather для асинхронных операций
- Улучшена производительность параллельных запросов к провайдерам

## [v1.4.1] — 2026-06-28

### 🔧 Улучшения
- Добавлен embedding-based reranker для LM Studio
- Повышена точность ранжирования результатов поиска

## [v1.4.0] — 2026-06-28

### 🚀 Major
- Deep Call Graph с глубиной обхода 2+ уровней
- Расширен анализ зависимостей символов (callers/callees)

## [v1.3.0] — 2026-06-28

### 🔧 Улучшения
- Мульти-провайдерный реранкинг: Ollama → LM Studio → RRF fallback
- Автоматическое переключение между провайдерами при недоступности

## [v1.2.0] — 2026-06-28

### 🚀 Major
- Production-ready релиз
- Agentic search v4 с улучшенной семантикой
- Система отслеживания прогресса индексации

## [v1.1.0] — 2026-06-22

### 🚀 Major
- RemoteEmbedder для удалённой генерации эмбеддингов
- Готовый инсталлятор для быстрого развёртывания

## [v1.0.0] — 2026-06-21

### 🚀 Major
- Первый релиз проекта
- Базовый семантический поиск по кодовой базе
- Интеграция с LanceDB для векторного хранения
