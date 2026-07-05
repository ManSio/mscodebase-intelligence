# AGENT DIARY — MSCodeBase Intelligence

## [2026-07-05 23:45] — [Type: Docs] — Cross-reference update: docs переехали в per-language папки

**Problem:** Документация реорганизована из плоской `docs/` + корень в `docs/ru/`, `docs/en/`, `docs/zh/` по языкам. Все кросс-ссылки, переключатели языков и пути к логотипам ссылались на старую структуру.

**Solution:** Обновлены все 40+ файлов:
- Логотипы: `../logo/` → `../../logo/` для файлов в `docs/*/`
- Языковые переключатели: новый формат с `../en/`, `../ru/`, `../zh/`
- Кросс-ссылки: `docs/INSTALL.md` → `INSTALL.md`, `../README.md` → `README.md`, `docs/architecture.md` → `ARCHITECTURE.md` и т.д.
- Файлы расследований: обновлены заголовки и ссылки
- `README.md` корневой: карта документации, навбар, структура проекта

**Tools Used:** read_file, edit_file, intel_log_incident
**Status:** ✅

## [2026-07-05 21:11] — [Type: Docs] — Полная i18n: все документы в 3 языках

**Problem:** Вся документация была только на русском или английском, без китайской версии.

**Solution:** Созданы .zh.md копии всех документов + .en.md для русскоязычных оригиналов.
Добавлены переключатели языков в каждый файл.

**Files created:** 21 новый файл (EN, ZH варианты для всех доков)

**Status:** ✅

## [2026-07-05 20:30] — [Type: Fix] — Full UI sweep: убран сырой JSON из всех 43 инструментов

**Problem:**
- intel_* инструменты возвращали сырой JSON (json.dumps) вместо Markdown
- _format_success_response добавлял огромный JSON-блок в каждый ответ
- debug_runtime_passport, get_runtime_counters — чистый JSON
- health_report: orphan files не чистились, search quality тесты падали по таймауту

**Solution:**
1. **intel_get_telemetry** — убран json.dumps, чистый Markdown
2. **debug_runtime_passport** — переписан в дашборд (Process/Project/Bridge/Registry/Env)
3. **_format_success_response** — убран JSON-блок, рекурсивный вывод с эмодзи (✓/✗/∅), вложенные dict/list до 10 элементов
4. **get_runtime_counters** — ui_formatter вместо json.dumps
5. **health_report** — orphan files авто-чистятся (105 очищено), search_quality timeout 8s→30s, git timeout 10s→30s
6. **install.py** — убивает старые MCP/LSP процессы и чистит stale-файлы

**Tools Used:** spawn_agent (3 parallel), edit_file, notify_change, grep, read_file
**Status:** ✅ Все 43 инструмента форматированы. Только 1 warning остался (logs dir — косметика)

---

## [2026-07-05 20:10] — [Type: Fix] — debug_runtime_passport → Markdown + health_report warnings fix

**Problem:**
1. `debug_runtime_passport` возвращал сырой JSON вместо Markdown-дашборда
2. health_report: orphan files (105) только детектились, но не удалялись из индекса
3. git execution_contract timeout был 10s — недостаточно для Windows
4. search_quality timeout был 8s — слишком мало для LM Studio

**Solution:**
1. `src/mcp/server.py`: debug_runtime_passport переписан на header/section/_val из ui_formatter
2. `src/core/health_report.py`: в _check_filesystem_sync добавлен вызов indexer.delete_file() для каждого orphan
3. `src/core/health_report.py`: git timeout 10→30s, search timeout 8→30s
4. `src/core/execution_contract.py`: все subprocess timeout=10→30

**Tools Used:** intel_get_runtime_status, get_health_report, read_file, edit_file, notify_change, diagnostics, terminal
**Status:** ✅

## [2026-07-05 17:30] — [Type: Feature] — UI Formatter + Централизация логов

**Problem:**
1. Логи писались в .codebase_indices/logs/ внутри каждого проекта — засоряли проект
2. Вывод инструментов был сырым JSON, без единого стиля

**Solution:**

### 🔄 Логи — централизованы
- `src/core/log_manager.py`: `get_log_dir()` теперь всегда ведёт в ext_root
