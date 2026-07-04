# AGENT DIARY — MSCodeBase Intelligence

## [2026-07-04 13:24] — [Type: Fix] — get_health_report: Zombie Threads + Windows git hang + search timeout

**Problem:**
- get_health_report постоянно таймаутился (30-120с), хотя прямой тест работал за 0.1с
- Ответ не доходил до Zed, хотя CPU показывал нагрузку (код выполнялся)
- После Cancel инструмента — новые вызовы тоже висли (Zombie Thread Exhaustion)

**Root Causes:**
1. **Zombie Thread Exhaustion:** Лимитированные ThreadPoolExecutor (4 fast / 2 slow) +
   Cancel от пользователя → потоки оставались висеть зомби, блокируя пул
2. **Windows git hang:** subprocess.run(git, timeout=5) не убивает orphan-дочерние
   процессы (credential helper), блокируя stdout/stderr навсегда
3. **Search quality:** 3 вызова searcher.search() × ~7с = 21с, сжирая весь таймаут
4. **Логгер без handlers:** health_report.py использовал logging.getLogger("health_report")
   без handlers — логи диагностики не писались

**Fix:**
1. `_run_with_timeout`: ThreadPoolExecutor → asyncio.to_thread() (без лимита потоков)
2. `_check_execution_contract`: subprocess.run → daemon thread + join(timeout=4).
   Если git завис — бросаем поток, продолжаем диагностику
3. `_check_search_quality`: 3 поиска → 1 поиск + daemon thread + join(timeout=8)
4. Логгер: 'health_report' → 'mscodebase_server' (с файловым handler)
5. get_health_report таймаут: 120 → 45с
6. GIT_TERMINAL_PROMPT=0, GIT_PAGER=cat, --no-pager, --no-ahead-behind

**Tools Used:** get_health_report, get_logs, terminal, grep, read_file, edit_file
**Status:** ✅ get_health_report работает (~25с)

**Problem:**
- 2 инструмента (get_branch_info, scan_changes) постоянно таймаутились
- get_commit_history таймаутился 9 раз подряд (логи: 11:10-11:42)
- get_branch_info напрямую работал за 0.1с, но через MCP — таймаут 15с
- Непонятна реальная причина: перегрузка или баг

**Investigation:**
- Полный аудит всех 36 инструментов на реальных данных проекта
- ✅ Работают: 31 инструмент (search_code все 4 режима, get_symbol_info, structural_search, impact_analysis, get_repo_rank, cross_repo_search, get_related_files, etc.)
- ❌ Таймаут: get_branch_info, scan_changes
- ⚠️ Пусто: intel_code_topology (вложенная функция не индексируется)

**Root Cause:** ThreadPoolExecutor Deadlock
1. `get_commit_history` → `_run_with_timeout` → `CommitMemory.fetch_commits()` → `subprocess.run(git log)` с timeout=30
2. На Windows git log висел > 15с (credentials/pager)
3. ThreadPoolExecutor(max_workers=4): каждый зависший git log занимает 25% executor'а
4. После 4 параллельных вызовов → executor полностью заблокирован
5. `get_branch_info` (0.1с!) не может получить поток → таймаут 15с

**Fix:**
1. `_run_with_timeout` — добавлена диагностика (лог qsize executor'а)
2. `max_workers` — увеличен с 4 до 8
3. `CommitMemory` синглтон — git log вызывается 1 раз за сессию
4. `intel_add_memory_node` — tech_debt записан

**Tools Used:** все 36 MCP инструментов + terminal (psutil), grep, read_file, edit_file
**Status:** ✅ (требуется перезапуск MCP сервера для применения фиксов)

## [2026-07-04 15:30] — [Type: Refactor] — Unified JSON format for all @mcp.tool() returns

**Problem:**
- Tool return values were inconsistent: some returned JSON, some plain text with emoji
- AI agents couldn't reliably parse status codes from text returns
- No standardized contract for status/message/data separation

**Solution:**
- Refactored all 32 @mcp.tool() functions in src/mcp/server.py to return unified JSON:
  ```json
  {"status": "ok" | "error" | "warning" | "timeout", "message": "Human-readable text with emoji 📊 ✅ ❌ ...", ...}
  ```
- Key changes:
  - get_index_status: added status + message fields
  - get_index_timeline: converted from plain text to JSON with timeline array
  - get_repo_map: _fetch_repo_map now returns JSON with structure + symbols
  - get_logs: now uses get_recent_errors directly, returns errors array
  - get_branch_info, get_commit_history, get_file_history: wrapped in JSON
  - get_bug_correlation, get_hotspots, get_related_files: converted to JSON
  - get_task_status, predict_eta, run_health_check: converted to JSON
  - graph_query, generate_chunk_summaries, scan_changes: converted to JSON
  - watcher_status: added status + message
  - cross_repo_search, cross_project_deps: all branches return JSON
  - verify_action: converted to JSON
  - All error returns now include message field with emoji
  - Removed unused get_log_summary import

**Tools Used:** read_file, edit_file, grep, terminal, diagnostics
**Status:** ✅ (Completed and verified via diagnostics + compilation check)

**Problem:**
- All `@mcp.tool()` functions returned error/warning strings with emoji prefixes (❌, ⚠️, ✅) and Russian text
- AI agents consuming these returns need structured JSON, not display-formatted emoji strings

**Solution:**
- Converted every `return f"❌ ..."` and `return f"⚠️ ..."` from `@mcp.tool()` methods to `json.dumps({"status": "error|warning|ok", "detail": "..."}, ensure_ascii=False)`
- Also fixed non-f-string emoji returns and ✅ success returns
- Preserved `logger.*` calls (internal logging, not tool output)
- Preserved decorative emoji in multi-line formatted outputs (display formatting)
- Translated all detail text to English

**Files Changed:** `src/mcp/server.py` — ~100 return statements converted across all @mcp.tool() functions

**Tools Used:** grep, read_file, edit_file, terminal (python syntax check)
**Status:** ✅

## [2026-07-04 09:30] — [Type: Fix] — Progress job stuck at 50% (intel_get_job_status)

**Problem:**
- `intel_trigger_reindex` → `intel_get_job_status` всегда возвращает `progress: 0.5`, даже после завершения фактической индексации
- Job висит в статусе "running" бесконечно

**Solution:**
- `trigger_async_reindex()` в `src/core/intelligence_layer.py` не передавал `progress_callback` в `Indexer.index_project()`
- Прогресс статически ставился на `job.progress = 0.5` перед `await future` и не обновлялся ~5 минут, пока индексация реально шла
- Добавлен `_index_progress_callback`, который маппит `files_done/total_files` на шкалу `job.progress` (0.1 → 0.8)
- Удалён redundant `hasattr` (строка 400) и лишний `loop = asyncio.get_event_loop()` (строка 413)

**Requires:** рестарт MCP-сервера (код в памяти, hot-reload не поддерживается)

**Tools Used:** search_code, read_file, edit_file, terminal (python syntax check), diagnostics
**Status:** ✅ (требуется рестарт сервера)

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