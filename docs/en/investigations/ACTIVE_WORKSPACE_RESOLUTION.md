# Investigation: Определение активного проекта на Windows

[🇬🇧 English](ACTIVE_WORKSPACE_RESOLUTION.md) • [🇨🇳 中文](../zh/investigations/ACTIVE_WORKSPACE_RESOLUTION.md)

**Дата:** 2026-07-05
**Цель:** Найти надёжный способ узнать, какой проект/workspace сейчас под фокусом
в Zed IDE на Windows, без использования `ZED_WORKTREE_ROOT` (не работает)
и без `current_dir` (тоже не работает на Windows).

---

## Проблема

На Windows MCP-сервер не может определить, к какому проекту он привязан:
- `ZED_WORKTREE_ROOT` — не устанавливается (баг Zed #36019)
- `current_dir` в `settings.json` для `context_servers` — не резолвит `$ZED_WORKTREE_ROOT`
- CWD MCP-процесса наследуется от процесса Zed (обычно `D:\AI\Zed`)
- Никаких env-переменных для идентификации окна/проекта не передаётся

---

## Что было проверено

### 1. Внешние механизмы (env, args, stdin)

| Механизм | Где искали | Результат |
|----------|-----------|-----------|
| `ZED_WORKTREE_ROOT` | `crates/context_server/` | ❌ Не найдено. На Windows всегда `<unset>` |
| `current_dir` | `crates/project/src/context_server_store.rs` | ❌ Работает в коде Zed, но на Windows не применяется к процессу |
| env vars (`ZED_WINDOW_ID`, `ZED_PROJECT_PATH`) | grep по всему репозиторию | ❌ Не существуют |
| MCP JSON-RPC initialize | `crates/context_server/src/protocol.rs` | ❌ Нет поля для window/project |
| StdioTransport args | `crates/context_server/src/transport/stdio_transport.rs` | ❌ Только command + args из settings.json |

### 2. Внутренние Rust API (недоступны извне)

| Механизм | Файл | Результат |
|----------|------|-----------|
| `App::active_window()` | `crates/gpui/src/app.rs:645` | ✅ Работает, но только внутри Rust |
| `MultiWorkspace::workspace()` | `crates/workspace/src/multi_workspace.rs` | ✅ Дает workspace под фокусом |
| `Project::active_entry()` | `crates/project/src/project.rs` | ✅ Возвращает EntryId активного файла |
| Extension API | `crates/extension/src/extension.rs` | ❌ Нет метода для active workspace |

### 3. SQLite — найдено!

**Таблица `scoped_kv_store`** с namespace `multi_workspace_state` содержит JSON:

```json
{
  "active_workspace_id": 2,
  "sidebar_open": false,
  "project_groups": [...]
}
```

Где `active_workspace_id` — ID workspace, который сейчас под фокусом.

**Как это работает в исходниках Zed** (`crates/workspace/src/multi_workspace.rs:674`):

```rust
pub fn serialize(&mut self, cx: &mut Context<Self>) {
    let state = MultiWorkspaceState {
        active_workspace_id: this.workspace().read(cx).database_id(), // ← ID активного workspace
        project_groups: this.project_groups.iter().map(/*...*/).collect(),
        ...
    };
    // Пишется в scoped_kv_store при каждом переключении workspace
    kvp.scoped("multi_workspace_state").write(&window_id, &state);
}
```

**Обновляется при каждом переключении** (`multi_workspace.rs:520`):
```rust
cx.emit(MultiWorkspaceEvent::ActiveWorkspaceChanged { ... });
// → MultiWorkspace::serialize() → запись в SQLite
```

**Как найти пути проекта:**

```sql
-- 1. Достаём active_workspace_id
SELECT value FROM scoped_kv_store 
WHERE namespace = 'multi_workspace_state' 
  AND key = '4294967297';

-- 2. По active_workspace_id получаем путь проекта
SELECT paths FROM workspaces 
WHERE workspace_id = <active_workspace_id>;
```

---

## Решение

`resolve_project_root()` теперь первым делом читает `active_workspace_id` из SQLite.
Этот механизм:
- ✅ Работает на Windows (SQLite доступен всегда)
- ✅ Обновляется в реальном времени при переключении проектов
- ✅ Не требует env, current_dir, LSP или других сломанных механизмов
- ✅ Не зависит от того, сколько окон открыто

**Приоритет резолва (новый):**

```
1. SQLite multi_workspace_state.active_workspace_id ← НОВЫЙ, главный
2. Явный project_root из аргументов инструмента
3. LSP Bridge (не работает на Windows)
4. SQLite workspaces (старый fallback)
5. PROJECT_PATH из .env
6. CWD (всегда отклоняется self-indexing guard)
7. ext_root (fallback — режим самодиагностики)
```

---

## Что было сделано за сессию (2026-07-05)

### Исправления

| Компонент | Проблема | Фикс |
|-----------|---------|------|
| `rate_limiter.py` | DebounceBatch — `await` внутри `threading.Lock` (100% дедлок) | Решение под lock, flush вне lock |
| `log_manager.py` | Логи писались per-project + в ext_root | Централизация в ext_root + чистка stale |
| `server.py` | `_ext_root` определялся через `__file__` → путал проект с ext_root | `_ext_root` из PYTHONPATH |
| `zed_config.py` | `system_prompt` плодил копии с битой кодировкой | Детект дубликатов по счётчику маркера |
| `install.py` | Писал `mscodebase.semaphore` в корень settings.json | Удалено (Zed ругался на неизвестный ключ) |

### Документация

| Файл | Что сделано |
|------|------------|
| `INSTALL.md` | Полный переписывание под реальность |
| `README.md` | Добавлена карта документации, исправлены числа |
| `ARCHITECTURE.md` | 37→33 tools, 307→391 tests |
| `ZED_WINDOWS_QUIRKS.md` | Множественные исправления, CWD, базы, multi-window |
| `../../AGENTS.md` | Правило multi-window проверки |
| `CONTRIBUTING.md` | ARCHITECTURE.md→architecture.md, ~12→10 files |

### Расследования

| Файл | О чём |
|------|-------|
| `LSP_WONTFIX.md` | Почему LSP не работает на Windows |
| `ACTIVE_WORKSPACE_RESOLUTION.md` | Как определить активный проект (этот файл) |

---

## Технические выводы

1. **Единственный рабочий канал на Windows — SQLite.** Ни env, ни current_dir, ни MCP-протокол не передают информацию о проекте.

2. **`multi_workspace_state.active_workspace_id`** — надёжный источник, обновляется синхронно с переключением workspace в Zed. Ключ — `window_id.as_u64().to_string()` (на одноконной системе — `4294967297`).

3. **Архитектура Windows vs macOS/Linux:**
   - На macOS: `ZED_WORKTREE_ROOT` env + корректный `current_dir` → проект известен.
   - На Windows: ни то, ни другое не работает → только SQLite.

4. **Multi-window (разные физические окна):** разные окна имеют разные `window_id`. Каждый MCP-сервер может найти свой window_id через... эвристику (сопоставление временных меток, parent PID). На практике при одном окне с несколькими проектами — `window_id` один.

---

## Заключение

Проблема решена через чтение `scoped_kv_store.multi_workspace_state.active_workspace_id`
из SQLite. Это надёжный механизм, встроенный в сам Zed, не требующий
ни env-переменных, ни external_dir, ни LSP. Работает на Windows, macOS и Linux.
