<img src="../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

# FAQ — MSCodeBase Intelligence

> Часто задаваемые вопросы. Основано на реальном опыте разработки и эксплуатации.

---

## 📦 Установка и запуск

### MCP-сервер не отвечает после установки

**Причина:** Zed не перезапущен. `window: reload` недостаточен.
**Решение:** File → Quit → открыть проект заново.

Логи: `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`

### После `python install.py` ничего не изменилось

**Причина:** Установщик скопировал файлы в расширение, но MCP-сервер уже запущен со старыми.
**Решение:** File → Quit → снова открыть проект. Только полный рестарт перезапускает MCP.

### Индекс пуст (0 чанков)

**Решение:** Выполнить `intel_trigger_reindex()` в Agent Panel. Подождать 1-5 минут.
Прогресс отслеживать через `intel_get_job_status(<job_id>)`.

---

## 🔍 Поиск и инструменты

### `search_code` возвращает 0 результатов

**Причины:**
- Индекс пуст → см. выше
- LM Studio не запущен → `intel_get_runtime_status()` покажет "offline"
- Проект не тот → проверь вывод `get_index_status()`

### `get_index_status()` показывает не мой проект

**Причина:** Определение проекта через SQLite — если в Zed открыто несколько проектов,
может выбрать не тот. Особенно на Windows, где нет `ZED_WORKTREE_ROOT`.

**Решение:** Закрыть все окна Zed, открыть только нужный проект.
Подробнее: `docs/investigations/2026-07-05-active-workspace-resolution.md`

### Инструмент возвращает сырой JSON

**Если это было в старой версии:** Исправлено. После версии `05de324` (2026-07-05)
все 43 инструмента форматируются в читаемый Markdown.
**Решение:** Запустить `python install.py` и перезапустить Zed.

---

## 🪟 Windows

### LSP не запускается (mscodebase-lsp)

**Причина:** Zed на Windows не может зарегистрировать кастомный LSP.
Требуется Rust/WASM-адаптер. `settings.json` бессилен.
**Статус:** WONTFIX. MCP-сервер работает полноценно без LSP.
Подробнее: `docs/investigations/2026-07-05-lsp-zed-1.9.0.md`

### Zed показывает "Restricted Mode"

**Решение:** Нажать "Trust and Continue". Поставить галочку "Trust all projects in..."
Иначе LSP не стартует, MCP не видит проект.

### MCP не перезапускается автоматически

**Решение:** Только File → Quit → снова открыть проект.
Auto-restart не поддерживается Zed на Windows.

### Проект определяется как "ext_root" (self-indexing)

**Причина:** resolve_project_root() не смог найти проект через SQLite.
**Решение:** Убедиться, что проект открыт в Zed. Проверить `LocalAPPDATA/Zed/db/0-stable/db.sqlite`.
Если там нет записей — возможно Restricted Mode.

---

## ⚡ Производительность

### Медленный поиск (>10s)

**Причины:**
- LM Studio на слабой машине (проверить `intel_get_telemetry()` → ping)
- Индекс не оптимизирован (запустить `intel_trigger_reindex()`)
- Слишком большой `limit` в `search_code` (рекомендуется 6-10)

### LLM Ping > 2000ms

**Решение:** Проверить LM Studio. Убедиться, что модель для эмбеддингов
(например, `BAAI/bge-m3`) загружена. Не использовать LLM-модели через LM Studio
для эмбеддингов — они медленные.

### Память > 500 MB

**Нормально:** LanceDB использует mmap-файлы. Windows держит их в памяти.
**Решение:** Перезапуск MCP освобождает память (File → Quit).

---

## 🐛 Баги и ошибки

### `ModuleNotFoundError: No module named 'src'`

**Причина:** PYTHONPATH не указывает на директорию расширения.
**Решение:** Запустить `python install.py` — он пропишет корректный PYTHONPATH.

### `ToolError: Refusing to index self`

**Причина:** Self-indexing guard — MCP защищается от индексации собственных исходников.
**Решение:** Открыть в Zed другой проект (не расширение).

### MCP завис после пачки notify_change

**Было в старой версии (до 2026-07-05):** Дедлок в DebounceBatch.
**Исправлено.** Если всё ещё происходит — проверь версию (`debug_runtime_passport` → BUILD_ID).
Решение: File → Quit.

---

## 🔗 Связанные документы

| Документ | Описание |
|----------|---------|
| `docs/INSTALL.md` | Установка для пользователей |
| `docs/architecture.md` | Архитектура проекта (10 слоёв) |
| `ZED_WINDOWS_QUIRKS.md` | Windows-специфика |
| `docs/HANDFOFF_TO_AI_AGENT.md` | Опыт разработки, архитектурные решения |
