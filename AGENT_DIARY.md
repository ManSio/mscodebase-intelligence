# AGENT DIARY — MSCodeBase Intelligence

## [2026-07-05 12:00] — [Type: Meta] — Architecture Freeze — v2.4 done

**Сессия: архитектурная стабилизация (16 коммитов, ~2500 строк).**

**Ключевые изменения:**
- Self-indexing guard: удалён `_SELF_INDEX_MARKER`, добавлен `_reject_self_index_target()`
- SystemArtifacts: единый модуль для системных файлов (4 уровня), file_guard.py переведён на него
- Passport: RUN_ID, BUILD_ID, PID в src/core/passport.py (core не импортирует MCP)
- ProjectContext: единый immutable snapshot проекта (state + index + bridge + runtime + health + memory + jobs)
- RuntimeCoordinator: can_execute() → ExecutionVerdict с полями ok, reason, state, retry_after, requires_reindex, warnings, recommended_action, confidence
- Architecture linter: 3 проверки (Core→MCP, Tool→Registry, stale refs)
- architecture-layers.md: 10 layer responsibilities
- 11 lifecycle тестов, 36/36 passed, 0 warnings (было 1745)
- Evidence loop rule в AGENTS.md
- get_runtime_counters() — счётчики для метрик

**Записано в проектную память:**
- INC-25BF: Self-indexing guard fix
- ADR: RuntimeCoordinator как единая точка входа
- ADR: Passport в core
- Tech debt: не все инструменты на Coordinator
- Tech debt: миграция .codebase_indices → .mscodebase

**План v2.5 (через 2 недели метрик):**
1. Полная наблюдаемость
2. Все инструменты через Coordinator
3. Статистика использования инструментов
4. Метрики качества поиска
5. Профилирование

**Без новых компонентов.**

**Status:** ✅ Architecture freeze until v2.5

---

## [2026-07-05 10:30] — [Type: Architecture] — ProjectContext + RuntimeCoordinator

**Problem:**
- Каждый tool собирал информацию о проекте самостоятельно
  (Registry + Bridge + Passport + Health + Memory), создавая копипасту.
- Не было единой точки "можно выполнять запрос?".

**Solution:**
- `src/core/project_context.py` — `ProjectContext.capture(path, services)`
  возвращает Snapshot: state, index, bridge, runtime, health, memory, jobs.
- `src/core/runtime_coordinator.py` — `RuntimeCoordinator.can_execute(path)`
  принимает решение: готов проект или нет. Использует Registry
  (состояние) + SystemArtifacts (системный путь).
- `src/mcp/tools/base.py` — `require_ready_project()` делегирует
  Coordinator-у.
- MCP tool переименован в `intel_get_project_context`.

**Architecture now:**
  Tool → Coordinator → can_execute() → Snapshot → logic
  Tool не знает Registry, Bridge, Passport — только Verdict + Snapshot.

**Tools Used:** write_file, edit_file, terminal, py_compile.
**Status:** ✅
