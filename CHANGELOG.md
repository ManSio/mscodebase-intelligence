# Changelog

All notable changes to this project will be documented in this file.

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
