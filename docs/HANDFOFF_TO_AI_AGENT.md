# Handoff: MSCodeBase Intelligence — Опыт и решения для AI-агента

> Этот документ — передача опыта между AI-агентами.
> Описывает архитектуру, проблемы, решения и подводные камни проекта.
> Читать ПЕРЕД началом любой работы с проектом.

---

## ⚡ Коротко о проекте

**MSCodeBase Intelligence** — расширение для Zed IDE (Windows), которое добавляет
семантический поиск кода через MCP-сервер. Пользователь — misha, Windows 11,
Zed 1.9.0, Python 3.14.3. Код в `D:\Project\MSCodeBase`.

---

## 🧠 Ключевое открытие: как определить активный проект на Windows

**Проблема:** MCP-сервер не знает, какой проект открыт в окне Zed.
`ZED_WORKTREE_ROOT` — не работает на Windows. `current_dir` — тоже.
Каждое окно Zed запускает свой MCP-процесс, но никаких env-переменных
для идентификации окна/проекта не передаётся.

**Решение:** Читать `scoped_kv_store` в SQLite Zed.

```sql
-- Берём active_workspace_id (какой проект под фокусом)
SELECT value FROM scoped_kv_store 
WHERE namespace = 'multi_workspace_state' 
  AND key = '4294967297';
-- → {"active_workspace_id":2, "project_groups":[...]}

-- По ID получаем путь
SELECT paths FROM workspaces WHERE workspace_id = 2;
-- → "D:\Project\MSCodeBase"
```

**Где внедрено:** `src/mcp/server.py`, функция `resolve_project_root()`.
Приоритет 0 (перед всем остальным).

**Как работает:** Zed пишет `multi_workspace_state` при каждом переключении
проекта (см. `crates/workspace/src/multi_workspace.rs:674` в исходниках Zed).

**Проверено:** работает на Windows с одним окном и несколькими проектами
во вкладках.

---

## 🔬 Полный аудит механизмов Zed (что работает, что нет)

| Механизм | Работает? | Доступен? | Источник в коде Zed |
|----------|-----------|-----------|---------------------|
| `ZED_WORKTREE_ROOT` env | ❌ Windows | ✅ | Не установлен на Windows (баг #36019) |
| `current_dir` subprocess | ❌ Windows | ✅ | `stdio_transport.rs:34` — не применяется |
| MCP JSON-RPC initialize | ❌ | ❌ | `protocol.rs` — нет полей для проекта |
| Extension API (WASM) | ❌ | ❌ | `extension.rs` — нет метода active_workspace |
| `multi_workspace_state` в SQLite | ✅ | ✅ | `multi_workspace.rs:674` — пишется при смене |
| `workspaces` таблица SQLite | ✅ | ✅ | `persistence.rs` — читается при восстановлении |
| `editors` таблица SQLite | ✅ | ✅ | Содержит открытые файлы per-workspace |
| `App::active_window()` | ✅ | ❌ (Rust API) | `app.rs:645` — только внутри процесса Zed |

**Вердикт:** Единственный внешний канал на Windows — SQLite.
Других нет и не будет (аудировано 9 файлов исходников Zed).

---

## 🐛 Дедлок в DebounceBatch (исправлен)

**Файл:** `src/core/rate_limiter.py`
**Проблема:** `_debounce_wait()` вызывал `await self._flush()` внутри
`with self._lock:`, а `_flush()` захватывал тот же `threading.Lock`.
`threading.Lock` не reentrant — второй захват на том же треде блокирует
event loop навсегда.

**Симптом:** MCP-сервер зависает через ~5 секунд после пачки `notify_change`.
Любые инструменты перестают отвечать.

**Фикс:** вынести `await self._flush()` за пределы `with self._lock:`
(через флаги `should_flush`, `should_exit`).

**Проверено:** 8 последовательных `notify_change` — 0 ошибок, 0 таймаутов.

---

## 🗄️ Где хранятся базы данных

| Данные | Путь | Кто создаёт |
|--------|------|-------------|
| **Векторный индекс (LanceDB)** | `<проект>/.codebase_indices/lancedb_v2/` | MCP-сервер |
| **Память проекта** (ADR, issues) | `<проект>/.codebase_indices/intelligence/` | MCP-сервер |
| **Логи** | `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\` | MCP-сервер |
| **База Zed (SQLite)** | `%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite` | Сам Zed (read-only) |

**Важно:** После v2.4.6 логи пишутся ТОЛЬКО в директорию расширения,
а не per-project. Старые per-project логи удаляются автоматически.

---

## 📦 Архитектура файлов

```python
# 33 core tools (class-based MCPTool) + 10 intel tools
src/mcp/tools/*.py         # 10 файлов, 33 класса
src/core/intelligence_layer.py  # 10 intel_* инструментов

# DI Container
src/core/di_container.py   # 15 services

# Индексатор + поиск
src/core/indexer.py        # LanceDB (векторная БД)
src/core/searcher.py       # BM25 + Dense + RRF (гибридный поиск)

# UI Formatting
src/utils/ui_formatter.py  # Единый стиль вывода для всех инструментов
```

---

## ⚠️ Windows-specific подводные камни

1. **Restricted Mode** — при первом открытии проекта Zed показывает диалог
   безопасности. Нажать "Trust and Continue". Иначе LSP/MCP не запускаются.

2. **MCP не перезапускается после kill'а** — единственный способ:
   File → Quit → открыть проект заново. `window: reload` недостаточно.

3. **`ZED_WORKTREE_ROOT` = null** — не работает на Windows. Решено через
   SQLite `active_workspace_id`.

4. **Множество окон** — если открыть проекты в РАЗНЫХ окнах, MCP-процессы
   не имеют идентификации. Решение: открывать проекты в ОДНОМ окне
   (через боковую панель "проекты").

5. **Auto-restart** — если MCP упал, Zed НЕ перезапускает его автоматически.
   Только File → Quit → снова открыть проект.

---

## ✅ Чек-лист для следующего агента

Перед началом работы:

- [ ] Прочитать `AGENT_DIARY.md` (первые 5 записей)
- [ ] Запустить `intel_get_runtime_status()` — проверить какой проект
- [ ] Запустить `intel_get_project_memory()` — изучить ADR и known_issues
- [ ] Если MCP не отвечает — не retry, а переключиться на grep/cat
- [ ] Пути: для MCP — `src\core\file.py`, для терминала — `src/core/file.py`

После задачи:
- [ ] `intel_log_incident()` — записать что сделано
- [ ] `notify_change(file_path=...)` — обновить индекс
- [ ] Обновить `AGENT_DIARY.md`

---

## 🔗 Полезные ссылки

| Что | Где |
|-----|-----|
| Установка | `docs/INSTALL.md` |
| Архитектура | `docs/architecture.md` |
| Windows quirks | `ZED_WINDOWS_QUIRKS.md` |
| Список инструментов | `README.md` → Documentation Map |
| Расследование LSP | `docs/investigations/2026-07-05-lsp-zed-1.9.0.md` |
| Расследование active_workspace | `docs/investigations/2026-07-05-active-workspace-resolution.md` |
| Метрики | `docs/telemetry.md` |
| Исходники Zed | `github.com/zed-industries/zed` |
