# Слои архитектуры — MSCodeBase Intelligence

[🇬🇧 English](../en/ARCHITECTURE_LAYERS.md) • [🇷🇺 Русский](ARCHITECTURE_LAYERS.md) • [🇨🇳 中文](../zh/ARCHITECTURE_LAYERS.md)

Каждый слой отвечает ровно на один вопрос.

```
 Layer 0: Filesystem        — какие файлы есть на диске?
 Layer 1: SystemArtifacts   — это системный путь?
 Layer 2: Bridge            — какой проект сообщил LSP?
 Layer 3: Registry          — какой Indexer принадлежит проекту?
 Layer 4: StateMachine      — в каком состоянии проект?
 Layer 5: RuntimeCoordinator — можно ли выполнять запрос?
 Layer 6: ProjectContext    — как выглядит проект сейчас?
 Layer 7: Passport          — какой процесс сейчас работает?
 Layer 8: Intel Layer       — что делать с этой информацией?
 Layer 9: AI Agent          — ответ пользователю
```

---

## Layer 0 — Filesystem

**Вопрос:** какие файлы есть на диске?
**Код:** `os.walk`, `Path.rglob`, `FileGuard`
**Не знает:** про индексы, про MCP, про LSP.

---

## Layer 1 — SystemArtifacts

**Вопрос:** это системный путь?
**Код:** `SystemArtifacts.is_system_path()`
**Не знает:** про Registry, Bridge, Runtime, Indexer.

4 подуровня защиты:
1. **Directory Guard** — `.mscodebase/`, `.codebase_indices/`, `.git/`, `node_modules/`
2. **Artifact Guard** — `chunk_summaries.json`, `incidents.json`, `project_memory.json`
3. **Feedback Guard** — файлы, созданные самим индексатором
4. **Embedding Guard** — финальная проверка перед эмбеддингом

**Правило:** любой файл внутри `.mscodebase/` или `.codebase_indices/` = НЕ индексируется.

---

## Layer 2 — Bridge (LSP→MCP)

**Вопрос:** какой проект сейчас сообщил LSP?
**Код:** `read_project_from_bridge()`, `write_active_project()`
**Не знает:** про индексы, про Runtime.

Bridge — временный файл (`~/.mscodebase/bridge/session_*.json`),
который LSP пишет при каждом didOpen/didSave. MCP читает
при необходимости определить project_root.

---

## Layer 3 — Registry (ProjectIndexerRegistry)

**Вопрос:** какой Indexer принадлежит этому проекту?
**Код:** `ProjectIndexerRegistry.get_indexer(path)`
**Не знает:** про MCP, про Bridge, про Runtime.

Per-project singleton Indexer-ы с LRU eviction (макс 5).
Каждый проект имеет свой Lock для LanceDB.

---

## Layer 4 — StateMachine

**Вопрос:** в каком состоянии проект?
**Код:** `ProjectIndexerRegistry.get_state()`, `wait_until_ready()`
**Не знает:** про Bridge, про MCP-запросы.

```
UNINITIALIZED → STARTING → INDEXING → READY → FAILED
```

---

## Layer 5 — RuntimeCoordinator

**Вопрос:** можно ли выполнять MCP-запрос?
**Код:** `RuntimeCoordinator.can_execute()`
**Не знает:** про структуру кода, про поиск.

Использует:
- SystemArtifacts (Layer 1) — путь не системный?
- Bridge (Layer 2) — LSP синхронизирован?
- Registry + StateMachine (Layer 3-4) — проект готов?

Возвращает `ExecutionVerdict`:
- `ok` — можно выполнять
- `reason` — причина (ready / system_path / project_not_ready / ...)
- `retry_after` — через сколько повторно
- `requires_reindex` — нужна переиндексация
- `warnings` — предупреждения

---

## Layer 6 — ProjectContext

**Вопрос:** как выглядит проект прямо сейчас?
**Код:** `ProjectContext.capture()`
**Не знает:** про MCP-запросы, не запускает операции.

Возвращает Snapshot:
- state, index (chunks/files/symbols), bridge, runtime (PID/uptime),
  health (warnings/errors), memory (incidents/ADRs), jobs

---

## Layer 7 — Passport

**Вопрос:** какой процесс сейчас работает?
**Код:** `debug_runtime_passport()` — MCP tool
**Не знает:** про состояние индекса.

Показывает: RUN_ID, BUILD_ID, PID, uptime, ext_root, project_root,
env (PROJECT_PATH, ZED_WORKTREE_ROOT, PYTHONPATH), guard result.

---

## Layer 8 — Intel Layer

**Вопрос:** что делать с информацией?
**Код:** `intel_get_runtime_status`, `intel_get_project_context`,
         `intel_explain_project_state`, `intel_predict_root_cause`
**Не знает:** про низкоуровневые детали.

Аггрегирует данные из нижних слоёв в готовые ответы.

---

## Layer 9 — AI Agent

**Вопрос:** какой ответ дать пользователю?
**Код:** система правил (AGENTS.md, SKILL.md)
**Не знает:** про внутреннюю архитектуру.

---

### 🔗 Связанные документы

| Документ | Описание |
|----------|----------|
| [README.md](../../README.md) | Основная документация, карта всех доков |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Архитектура проекта, DI, слои |
| [TELEMETRY.md](TELEMETRY.md) | Метрики и телеметрия |
| [CHANGELOG.md](CHANGELOG.md) | История версий |
