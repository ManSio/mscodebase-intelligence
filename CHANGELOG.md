# Changelog

All notable changes to this project will be documented in this file.

## [v2.3.2] — 2026-07-05 — Multi-Root Awareness + Self-Indexing Guard

### 🐛 Critical Bug: Self-Indexing Zed Install Dir
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

### 🧪 Testing: 306 passed + 1 pre-existing failure
- Все предыдущие тесты прошли без изменений.
- `test_expected_message_mismatch` — pre-existing, не связан с v2.3.2.

### 📚 Migration
- После обновления: `sync_to_installed.bat --full` + перезапуск Zed.
- Если `D:\AI\Zed\.codebase_indices/` содержит мусор от self-indexing —
  можно удалить вручную: `rm -rf /d/AI/Zed/.codebase_indices`.
- Чтобы Zed точно открыл проект: `cmd+shift+p` → "Open Project" →
  выбрать `D:\Project\MSCodeBase` (создаст `.zed/` workspace marker).

---

## [v2.3.1] — 2026-07-05 — Startup Hang Fix + DebounceBatch Per-Project

### 🐛 Critical Bug Fixes
- **`lsp_main.py:did_change_watched_files`** — `if _services is None` бросал `NameError` (глобальная `_services` не существует в per-workspace архитектуре). Заменено на lookup в `_services_per_workspace[uri]` с fallback на первый доступный. Без этого watcher-events падали с NameError при первом же срабатывании.
- **`lsp_main.py:did_change`/`did_close`/`did_save`** — workspace_uri и project_root НЕ передавались в `_execute_file_indexing` (только `did_open` передавал). В multi-window это значит, что все индексируемые файлы попадали в default Indexer. **Исправлено** — все четыре хука теперь пробрасывают `getattr(ls, "_workspace_uri", "")` и `getattr(ls, "_project_root", None)`.
- **`lsp_main.py:_execute_file_indexing`** — `services.resolve(type("_IndexerFactory", (), {})) if False else ...` (мёртвый код с анонимным type) заменён на прямой `_get_factory(services)`. Аналогично `services.resolve(type("ProjectRootKey", (), {}))` → `services.resolve(ProjectRootKey)`.
- **`search_tools.py:_agentic_search`** — `self.searcher` и `self.symbol_index` НЕ существуют в базовом `MCPTool` (Indexer/Searcher per-project через registry). Заменено на `self.resolve_searcher()` / `self.resolve_symbol_index()`. Без этого agentic_search падал с AttributeError.
- **`graph_tools.py:GraphQueryTool`** — `services.resolve(SymbolIndex)` + `services.resolve(Indexer)` в `__init__` (Indexer больше не singleton) заменены на `self.resolve_symbol_index()` / `self.resolve_indexer()` per-call. Fallback `Path.cwd()` для project_root убран.
- **`mcp/server.py:IntelligenceLayer`** — `services.resolve(Indexer/Searcher/SymbolIndex)` (все три не зарегистрированы) заменены на `resolve_indexer_for_request(services)`. Без фикса 10 intel_* tools не регистрировались (warning "Intel layer not registered").
- **`mcp/server.py:33+13` → `33+10`** — корректный счёт (10 intel tools, а не 13).

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

### 🧪 Testing: 307 passed
- `tests/test_di_container.py::test_creates_all_services` — убран `DebounceBatch` из списка (больше не singleton).
- `tests/test_di_container.py::test_debounce_batch_uses_searcher` — переписан: batch берётся из `indexer.bm25_batch`, а не через `services.resolve(DebounceBatch)`.
- Все остальные 305 тестов прошли без изменений.

### 📚 Migration Notes
- После обновления: `sync_to_installed.bat --full` + перезапуск Zed.
- Никаких ручных правок `settings.json` не требуется (всё через `patch_zed_settings`).

---

## [v2.3.0] — 2026-07-05 — Multi-Window Support & Hardening

### 🏗️ Architecture: Multi-Window
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

### 🐛 Bug Fixes (audit INC-53EC, 19 issues)
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

### 🔧 Zed Settings
- `current_dir` убран из `patch_zed_settings` (Zed не подставляет
  `$ZED_WORKTREE_ROOT` в `current_dir` — bug #36019). `resolve_project_root`
  обрабатывает приоритеты сам: PROJECT_PATH env → bridge → CWD → ext_root.
- `fix_zed_settings.bat` (new) — патчит существующий `settings.json` пользователя
  (удаляет `current_dir` с бэкапом).
- Self-indexing guard: PROJECT_PATH указывает на MSCodeBase → warning в логах.

### 🧪 Testing: 325 → 307 passing (+ 11 new = 318; 11 deprecated, минус = 307)
- `test_resource_monitor.py` (new, 11 tests):
  - `ResourceMonitor`: sample, throttle, pressure thresholds, summary, singleton
  - `ProjectIndexerRegistry`: singleton per path, LRU eviction, pressure eviction,
    explicit evict, stats (hits/misses/evictions)
- `test_health_report.py`: degraded status, total_symbols/embedder_mode алиасы,
  orphan-files detection, git log cwd, fallback embedder warning
- `test_integration.py`: `isolated_indexer` использует `temp_project` как
  `project_path` (был баг — FileGuard отвергал файлы как "not in project")
- `test_di_container.py`: `Indexer`/`Searcher` теперь per-project через registry

### 📚 Documentation
- README: tests badge 325 → 307, добавлен Multi-Window в features
- `docs/architecture.md`: секция "Multi-Window Registry" + ResourceMonitor
- CHANGELOG: этот файл
- `pyproject.toml`: bumped to v2.3.0
- AGENT_DIARY.md: 3 записи (аудит + multi-window + resource monitor)

### ⚠️ Migration Notes
- После обновления запустите `fix_zed_settings.bat` для удаления
  `current_dir` из `~/.config/Zed/settings.json` (или `%APPDATA%\Zed\settings.json`).
- `sync_to_installed.bat --full` для синхронизации с установленной копией.
- Перезапустите Zed для подхвата новых версий.

---

## [v2.2.0] — 2026-07-04 — Architecture Modernization

### 🏗 Architecture Rewrite
- **DI Container:** `ServiceCollection` with Constructor Injection (15 services)
- **server.py:** 3,100 → **220 lines** (-93%). God Object eliminated.
- **37 tools** decoupled into 10 domain-specific files in `src/mcp/tools/`
- **error_boundary** decorator: unified JSON responses, real `asyncio.wait_for` timeout
- **DebounceBatch:** BM25 реиндексация через 500ms debounce (не на каждый файл)
- **SlidingWindowRateLimiter:** защита от VFS-петель (10 req/sec max)
- **CircuitBreaker:** CLOSED/OPEN/HALF_OPEN для LM Studio (5 failures → 30s recovery)
- **hybrid_server.py:** DEPRECATED (вся логика в DI Container + lsp_main.py)

### 🔧 Improvements
- `lsp_main.py` — 4 глобальные переменные → DI container (_services)
- `notify_change` — Rate Limiter + DebounceBatch вместо немедленной BM25
- `get_index_progress` — progress tracking как module-level exports
- `read_live_file` — новый инструмент (чтение из LSP VFS с disk fallback)
- `_resolve_project_path` → standalone `resolve_project_root()`
- `GIT_ASKPASS=echo` + `CREATE_NO_WINDOW` — защита от Git Hang на Windows
- `_is_complex_query` — исправлена: русская грамматика → token-based + English W-words

### 🧪 Testing
- 52 new unit tests for:
  - `error_handler.py` — ToolError, error_boundary (async + sync), timeout, retries
  - `rate_limiter.py` — SlidingWindow, DebounceBatch, CircuitBreaker (all states)
  - `di_container.py` — ServiceCollection, 15 DI services, Searcher↔Indexer cycle
- Total: **325 tests**

### 📚 Documentation
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

### 🔧 Improvements
- `get_health_report`/`index_health` — `project_root` опционален (fallback на `$PROJECT_PATH`)
- `notify_change` — правильный резолв путей от корня проекта (не CWD)
- `_resolve_project_path()` — централизованный helper для резолва корня проекта
- Централизованная обработка путей через `PROJECT_PATH` env var (устанавливается Zed)
- `install.py` — clean-up: удалён дублирующий код LSP (теперь в `patch_zed_settings`)

### 📚 Documentation
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

## [v2.0.0] - 2026-06-28

### 🚀 Major
- Гибридная архитектура LSP + MCP: единый процесс с общей памятью вместо отдельных серверов
- Полный отказ от межпроцессного взаимодействия — снижение задержек и упрощение деплоя

### ⚠️ Breaking Changes
- Требуется миграция с предыдущей архитектуры на единый LSP+MCP процесс
- Изменены точки интеграции с редактором (больше нет отдельного MCP-сервера)
- Обновлён формат конфигурации

## [v1.4.2] - 2026-06-28

### 🔧 Improvements
- Миграция с ThreadPoolExecutor на asyncio.gather для асинхронных операций
- Улучшена производительность параллельных запросов к провайдерам

## [v1.4.1] - 2026-06-28

### 🔧 Improvements
- Добавлен embedding-based reranker для LM Studio
- Повышена точность ранжирования результатов поиска

## [v1.4.0] - 2026-06-28

### 🚀 Major
- Deep Call Graph с глубиной обхода 2+ уровней
- Расширен анализ зависимостей символов (callers/callees)

## [v1.3.0] - 2026-06-28

### 🔧 Improvements
- Мульти-провайдерный реранкинг: Ollama → LM Studio → RRF fallback
- Автоматическое переключение между провайдерами при недоступности

## [v1.2.0] - 2026-06-28

### 🚀 Major
- Production-ready релиз
- Agentic search v4 с улучшенной семантикой
- Система отслеживания прогресса индексации

## [v1.1.0] - 2026-06-22

### 🚀 Major
- RemoteEmbedder для удалённой генерации эмбеддингов
- Готовый инсталлятор для быстрого развёртывания

## [v1.0.0] - 2026-06-21

### 🚀 Major
- Первый релиз проекта
- Базовый семантический поиск по кодовой базе
- Интеграция с LanceDB для векторного хранения
