# AGENT DIARY — MSCodeBase Intelligence

## [2026-07-04 02:15] — [Type: Fix|Arch] — LSP→MCP Bridge: auto project detection без хардкода

**Problem:**
- Windows: `current_dir: "$ZED_WORKTREE_ROOT"` в context_servers не резолвится (баг Zed #36019)
- MCP при старте не знал корень проекта — падал на ext_root (`D:\AI\Zed\...`)
- Индекс работал только если случайно вызывали `intel_trigger_reindex`
- Новые пользователи: не работало "из коробки", требовалось ручное `.zed/settings.json`

**Solution: LSP→MCP Bridge через temp-файл**
1. **LSP** (`lsp_main.py:on_initialize`) — получает `root_uri` от Zed (LSP протокол, работает везде), пишет в `~/.mscodebase/bridge/session_{parentPID}.json`
2. **MCP** (`server.py:_resolve_project_path`) — добавляет шаг 1.5: читает bridge с polling до 3 сек
3. **Bridge** (`src/core/lsp_project_bridge.py`) — общий модуль с атомарной записью (`os.replace`), UUID сессии, валидацией возраста, fallback на хеш argv при `psutil.AccessDenied`

**Edge Cases закрыты (аудит Gemini):**
- Race condition (MCP быстрее LSP) — polling 50ms × 60 = 3 сек
- Два окна Zed — parent PID как ключ файла
- Stale PID reuse — session_id + timestamp в JSON
- Race чтения-записи — `os.replace()` атомарно
- psutil AccessDenied — fallback на хеш argv + CWD
- Auto cleanup — файлы старше 5 мин удаляются при старте

**Files Changed:**
- `src/core/lsp_project_bridge.py` — НОВЫЙ (100 строк)
- `src/lsp_main.py` — +6 строк в `on_initialize`
- `src/mcp/server.py` — +12 строк в `_resolve_project_path`

**Tools Used:** write_file, edit_file, terminal (python syntax check)

**Status:** ✅ (синтаксис валиден, bridge тест пройден, требуется перезапуск Zed)