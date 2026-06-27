# AGENT DIARY — MSCodeBase Intelligence

---

## [2026-06-27 15:30] — [Type: Refactor/Feature] — Оживление зомби-модулей + context_search

**Проблема:** Несколько модулей были мёртвым кодом или имели бессмысленные реализации:
1. `chunker.py` — дублировал `parser.py`, но хуже (содержал `pass` в AST-логике)
2. `search.py` — `HybridSearchEngine` с RRF нигде не использовался
3. `reranker.py` — `_contains_technical_terms()` матчило `(`, `)`, `.`, `;` — т.е. любой код
4. `context_engine.py` — `MAX_CONTEXT_CHARS = 3000` — слишком мало
5. Не было MCP-инструмента для поиска похожего кода

**Решение:**
- Удалён `chunker.py` (мёртвый код, 0 импортов)
- Удалён `search.py` (мёртвый `HybridSearchEngine`, 0 импортов)
- RRF fusion добавлен прямо в `searcher.py` как метод `_reciprocal_rank_fusion()`
- `hybrid_search()` теперь использует RRF по умолчанию (с fallback на реранкер)
- Исправлен `_contains_technical_terms()` — теперь ищет реальные паттерны (def, class, async, SQL, API)
- Добавлен MCP-инструмент `context_search(selected_code)` — поиск похожего кода
- `MAX_CONTEXT_CHARS` увеличен с 3000 до 8000
- `context_engine` теперь показывает RRF-скоры и сжимает длинные чанки
- Исправлен `test_mutation_core.py` — тесты обновлены под реальные типы

**Инструменты:** grep, read_file, edit_file, delete_path, spawn_agent, pytest

**Файлы изменены:**
- `src/core/chunker.py` — УДАЛЁН
- `src/core/search.py` — УДАЛЁН
- `src/core/searcher.py` — добавлен RRF, context_search
- `src/core/reranker.py` — исправлен _contains_technical_terms
- `src/core/context_engine.py` — MAX_CONTEXT_CHARS 3000→8000, RRF scores
- `src/mcp/server.py` — добавлен MCP-инструмент context_search
- `tests/test_mutation_core.py` — исправлены сломанные тесты
- `README.md` — обновлено дерево модулей

**Уроки:**
- RRF (Reciprocal Rank Fusion) устойчивее rank-based scoring — не требует нормализации скоров
- Мёртвый код нужно удалять, не хранить «на всякий случай»
- Тесты должны мокать публичный API (hybrid_search), а не внутренние методы (vector_search)

**Статус:** ✅

---

## [2026-06-27 17:00] — [Type: Feature] — Централизованное логирование + MCP-инструмент get_logs

**Проблема:**
1. Нет файлового лога — все логи ушли в stderr и терялись при перезапуске Zed
2. Нет привязки логов к проекту и времени
3. Нет способа быстро узнать что сломалось без чтения файлов
4. `StatusReporter` — мёртвый код (нигде не используется)

**Решение:**
- Создан `src/core/log_manager.py`:
  - `setup_project_logging()` — RotatingFileHandler (2MB × 3 файла) в `.codebase_indices/logs/<project>.log`
  - Привязка каждой записи к проекту: `[проект] модуль: сообщение`
  - Автоочистка логов старше 7 дней
  - `get_recent_errors()` — читает только хвост (64KB), не грузит систему
  - `get_log_summary()` — краткая сводка для MCP
- Добавлен MCP-инструмент `get_logs(project_root)` — просмотр ошибок
- Подключено в `main.py`, `lsp_main.py`, `server.py` (при старте и переключении проекта)

**Инструменты:** grep, read_file, edit_file, terminal, diagnostics

**Файлы изменены:**
- `src/core/log_manager.py` — НОВЫЙ
- `src/mcp/server.py` — get_logs, setup_project_logging при старте
- `src/main.py` — setup_project_logging при старте
- `src/lsp_main.py` — setup_project_logging при старте

**Уроки:**
- Логи должны быть файловыми с ротацией — stderr теряется
- Чтение хвоста файла (64KB) — лёгковесно, не грузит систему
- Привязка к проекту критична для мультипроектности

**Статус:** ✅

---

## [2026-06-27 16:00] — [Type: Feature/Fix] — Полный рефакторинг install.py + фикс dim(384→1024)

**Проблема:**
1. Тесты падали с `dim(384) vs dim(1024)` — моки возвращали 384-мерные векторы, а LanceDB схема требует 1024
2. `install.py` — унылый вывод без прогресса, не чистил stale-файлы, не останавливал процессы
3. `_clean_stale_files` склеился с `_stop_extension_processes` (баг при вставке)

**Решение:**
- Все моки `384` → `1024` в тестах и fallback-вектор в `remote_embedder.py`
- Полный рефакторинг `install.py` с TUI:
  - Цветной ANSI-вывод (рамки, иконки, подсветка)
  - Прогресс-бар `ProgressBar` с процентами и ETA
  - Спиннер `Spinner` для долгих операций
  - `_stop_extension_processes()` — убивает MCP/LSP процессы перед обновлением
  - `_clean_stale_files()` — удаляет файлы, которых нет в исходниках
  - `run_cmd_with_progress()` — команды со спиннером
- 24/25 тестов проходят (1 skipped — требует LM Studio)

**Инструменты:** read_file, edit_file, terminal, diagnostics

**Файлы изменены:**
- `install.py` — полный рефакторинг с TUI
- `src/core/remote_embedder.py` — fallback 384→1024
- `tests/test_searcher.py` — мок 384→1024
- `tests/test_integration.py` — мок 384→1024

**Уроки:**
- Размерность векторов должна быть консистентной во всех слоях
- install.py ДОЛЖЕН убивать процессы перед копированием файлов
- Stale-файлы в ZED_EXT_DIR — реальная проблема при удалении модулей

**Статус:** ✅

---

## [2026-06-27 14:30] — [Type: Bug Fix] — Исправлен баг prune_deleted_files

**Проблема:** `prune_deleted_files` вызывался из LSP с set из одного элемента (удалённый файл), что приводило к удалению ВСЕХ остальных файлов из базы.

**Решение:**
- Добавлена защита от пустого set в `prune_deleted_files`
- Добавлен метод `delete_file(rel_path_str)` для безопасного удаления одного файла
- LSP `_process_watched_changes` теперь использует `table.delete()` напрямую

**Инструменты:** grep, read_file, get_symbol_info, edit_file, pytest, scan_changes

**Файлы изменены:**
- `src/core/indexer.py` — добавлен `delete_file()`, защита в `prune_deleted_files()`
- `src/lsp_main.py` — использует `table.delete()` вместо `prune_deleted_files`
- `tests/test_indexer_project_path.py` — 4 новых теста

**Уроки:**
- `prune_deleted_files` требует ПОЛНЫЙ набор файлов на диске, не один элемент
- Всегда проверяй edge cases при работе с set operations

**Статус:** ✅

---

## [2026-06-27 14:15] — [Type: Bug Fix] — Исправлен баг Indexer.project_path

**Проблема:** LSP-сервер при каждом `Ctrl+S` падал с `AttributeError: 'Indexer' object has no attribute 'project_path'` потому что `Indexer.__init__` не сохранял `project_path`.

**Решение:**
- Добавлен `project_path` параметр в `Indexer.__init__` с fallback
- `switch_project` теперь обновляет `self.project_path`
- LSP и MCP серверы передают `project_path` при создании Indexer

**Инструменты:** grep, read_file, edit_file, pytest, diagnostics

**Файлы изменены:**
- `src/core/indexer.py` — `project_path` в `__init__` и `switch_project`
- `src/lsp_main.py` — передаёт `project_path=project_root`
- `src/mcp/server.py` — передаёт `project_path=ext_root`
- `tests/test_indexer_project_path.py` — 6 тестов

**Уроки:**
- Все модули создающие Indexer должны передавать `project_path`
- Fallback в `__init__` спасает от обратной несовместимости

**Статус:** ✅

---

## [2026-06-27 13:45] — [Type: Bug Fix] — Исправлен watcher_status

**Проблема:** `watcher_status` падал с `AttributeError: 'NoneType' object has no attribute 'is_alive'` когда `_scanner_thread = None`.

**Решение:** `getattr(embedder, "_scanner_thread", None)` + проверка `is not None` перед `.is_alive()`

**Инструменты:** read_file, edit_file, diagnostics

**Файлы изменены:** `src/mcp/server.py`

**Уроки:**
- `hasattr()` возвращает `True` даже если атрибут `None`
- Всегда проверяй `is not None` перед вызовом методов

**Статус:** ✅

---

## [2026-06-27 13:30] — [Type: Docs] — Полное обновление документации

**Изменено:** 11 файлов документации синхронизированы с кодом

**Уроки:**
- Документация должна отражать текущую структуру
- Удалены ссылки на несуществующие `docs/` файлы

**Статус:** ✅

---

## [2026-06-27 13:00] — [Type: Bug Fix] — Исправлен @mcp.prompt() и assistant→agent

**Проблемы:**
1. `@mcp.prompt()` был вне функции где `mcp` определён → `NameError`
2. `install.py` писал в устаревший блок `assistant` вместо `agent`

**Решение:**
1. Декоратор перемещён в `create_mcp_server()`
2. `install.py` и `zed_config.py` мигрированы на `agent`

**Уроки:**
- MCP декораторы должны быть внутри функции где объект `mcp` существует
- Zed актуальных версий использует `agent`, не `assistant`

**Статус:** ✅

---

## [2026-06-27 14:45] — [Type: Audit] — Полный аудит проекта по новым правилам

**Чек-лист выполнен:**
- get_index_status + get_repo_map (reconnaissance)
- grep + get_context + read_file (bug hunting)
- get_symbol_info(Indexer) (impact analysis)
- scan_changes + get_index_status (post-patch sync)
- pytest + diagnostics (верификация)
- 6 новых тестов написаны

**Найденные проблемы:**
1. prune_deleted_files с одним элементом удаляет все файлы — ИСПРАВЛЕНО
2. Нет delete_file() для одиночного удаления — ДОБАВЛЕНО
3. Тесты падают из-за размерности 384 vs 1024 — известная проблема

**Alembic/Aerich:** не найдены. Проект использует validate_lancedb_schema().

**Уроки:**
- Всегда веди дневник
- Проверяй edge cases при работе с set operations
- Размерность векторов в тестах должна совпадать с продакшеном

**Статус:** ✅

---

*Дневник ведётся в хронологическом порядке. Последняя запись сверху.*
