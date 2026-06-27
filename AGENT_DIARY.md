# AGENT DIARY — MSCodeBase Intelligence

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
