# AGENT DIARY — MSCodeBase Intelligence

## [2026-07-03 23:45] — [Type: Fix|Audit] — ETA, баги путей, verify_action, аудит 4 багов

**Problem:**
- `get_index_progress` не показывал ETA (Estimated Time) — отсутствовал расчёт
- `notify_change` читал PROJECT_PATH напрямую без фильтра `$ZED` → краш при нерезолвленной переменной
- `_resolve_project_path` при CWD==ext_root сразу возвращал ext_root без попытки восстановления
- `verify_action` использовал `**kwargs` → ломал JSON Schema для FastMCP
- Docstring: `get_repo_rank` обещал `top_k=20`, код использовал `10`
- Docstring: `index_project_dir` упоминал Watcher, но он отключён (LSP вместо него)

**Solution:**
1. ETA: Добавлен расчёт `elapsed = now - started_at`, `eta_remaining = elapsed / percent * (100 - percent)` с форматированием "~X мин Y сек"
2. notify_change: Переведён на `_resolve_project_path()` вместо `os.environ.get("PROJECT_PATH")` — фильтрация `$ZED`
3. _resolve_project_path: Добавлен .git heuristic, ZED_WORKTREE_ROOT env check, адекватный fallback на CWD с warning
4. verify_action: `**kwargs` → `kwargs: Optional[Dict[str, Any]] = None` для корректной Pydantic-схемы
5. Docstring: `get_repo_rank` исправлен на top_k=10, комментарий о ext_root актуализирован
6. `mscodebase_rules` prompt: обновлён — post-modification sync через notify_change вместо index_project_dir

**Tools Used:** read_file, edit_file, intel_get_runtime_status, get_index_status, search_code, get_symbol_info, spawn_agent (аудит), diagnostics
**Status:** ✅

## [2026-07-03 23:11] — [Type: Fix|Refactor] — Консолидация архитектуры: фикс путей проекта и download_model.py

**Problem:**
- `download_model.py` — циклическая перекачка 2-3GB модели при каждой сессии, HF кэш удалялся принудительно
- `server.py` — карта проекта содержала директорию расширения (`ext_root`) вместо проекта пользователя в 5+ местах
- `_resolve_project_path` — опасный fallback на `ext_root` без проверки

**Solution:**
- `download_model.py`: введён персистентный cache_dir (`~/.cache/mscodebase/hf_models`), `--purge-cache` и `--force` флаги, разорван цикл перекачки
- `server.py`: заменены 8 мест где `ext_root` использовался вместо `_base_project`/`_resolve_project_path()`:
  - `ProjectRegistry.register(ext_root)` → `_base_project`
  - `ProjectIntelligenceLayer(project_path=ext_root)` → `_base_project`
  - `IndexGuard(initial_db_path, ext_root)` → `_base_project`
  - `setup_project_logging(ext_root)` → `_base_project`
  - `notify_change` fallback → `_resolve_project_path()`
  - `_get_searcher` → `_resolve_project_path()`
  - `run_health_check(ext_root)` → `_resolve_project_path()`
  - `graph_query(ext_root)` → `_resolve_project_path()`
- `_resolve_project_path` теперь проверяет что CWD != ext_root, warning если PROJECT_PATH не установлен

**Tools Used:** read_file, edit_file, write_file, search_code, grep, intel_log_incident (2x), diagnostics
**Status:** ✅

## [2026-07-03 22:30] — [Type: Refactor] — Консолидация поисковых инструментов 42→20

**Problem:** 42 разрозненных инструмента, LLM путалась между 5 видами поиска

**Solution:** 
- `smart_search`, `deep_search`, `context_search` → DEPRECATED обёртки над `search_code(mode)`
- Единая точка входа: `search_code(query, mode="auto"|"fast"|"quality"|"deep"|"context")`
- Добавлена временная фильтрация (since/before kwargs)
- Backward compatibility через deprecated-обёртки

**Tools Used:** read_file, edit_file, grep, structural_search
**Status:** ✅
