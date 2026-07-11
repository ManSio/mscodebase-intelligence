---
name: mscodebase-rules
description: "Tool selection rules for the Zed AI agent. 57 registered tools: 14 High-Level Intel layer + 40 Low-Level Core MCP + 3 Diagnostic. Architecture layers: RuntimeCoordinator → ProjectContext → StateMachine → SystemArtifacts. Use search_code(mode=...) for all semantic search."
---

# MSCodeBase Tool Selection Rules (57 tools)

## Architecture Overview

```
RuntimeCoordinator.can_execute()           ← можно ли выполнять запрос?
    ↓
ProjectContext.capture()                   ← полный снэпшот проекта
    ↓
StateMachine (UNINITIALIZED→READY→FAILED)  ← жизненный цикл проекта
    ↓
SystemArtifacts.is_system_path()           ← защита от feedback loop
    ↓
MCP Tool Execution
```

## High-Level Intel Layer (14 tools)

Аналитические, агрегирующие инструменты. Заменяют несколько low-level вызовов одним.

| Tool | Что даёт |
|---|---|
| `intel_get_runtime_status` | Статус рантайма, ИИ-провайдеров и индексов за 1 вызов |
| `intel_trigger_reindex` | Async fire-and-forget переиндексация |
| `intel_get_job_status` | Статус фоновой задачи по job_id |
| `intel_code_topology` | Граф вызовов + статический анализ символа (<2 сек) |
| `intel_predict_root_cause` | Root Cause Engine по логам ошибки |
| `intel_analyze_incident` | Поиск аналогичных инцидентов из прошлого |
| `intel_get_project_memory` | Карта памяти проекта (ADRs, Known Issues, Tech Debt) |
| `intel_log_incident` | Запись инцидента в историю проекта |
| `intel_add_memory_node` | Добавление записи в проектную память |
| `intel_get_project_context` | **Единый снэпшот проекта** — state + index + bridge + health + memory + jobs |
| `intel_explain_project_state` | Человекочитаемый диагноз состояния проекта |
| `intel_get_hotspots` | Топ-5 файлов с баг-нагрузкой |
| `intel_get_telemetry` | Телеметрия: per-tool метрики, ресурсы |
| `intel_tool_health` | Панель здоровья инструментов |
| `intel_execution_timeline` | Лента последних действий системы |

## Low-Level Core MCP (33 tools)

### Search & Index
| Tool | Purpose |
|---|---|
| `search_code(query, mode=fast/quality/deep/context/auto)` | Semantic search by concept |
| `cross_repo_search(query)` | Multi-project search with @-mentions |
| `get_symbol_info(query)` | Call graph: definition + callers + callees |
| `impact_analysis(symbol)` | Risk: score, affected files, depth |
| `get_repo_map(project_root)` | File tree + structural symbols |
| `structural_search(project_root, pattern=...)` | AST pattern matching (13 patterns) |
| `get_related_files(file_path)` | Related files by co-change history |
| `graph_query(query_type, target)` | GraphRAG queries over code graph |

### Project & Indexing
| Tool | Purpose |
|---|---|
| `get_index_status(project_root)` | Database state + chunk count |
| `get_index_progress()` | Async indexing progress |
| `get_index_timeline()` | Index build history |
| `index_health(project_root)` | Detailed index health |
| `index_project_dir(path)` | Sync reindex (blocking) |
| `notify_change(file_path)` | Incremental index update (after edit) |
| `watcher_status()` | File watcher health |
| `submit_background_task(task_type)` | Submit async task |

### Git & History
| Tool | Purpose |
|---|---|
| `get_commit_history(project_root, limit)` | Recent commits |
| `get_file_history(file_path)` | File change history |
| `get_branch_info(project_root)` | Branch info |
| `scan_changes(project_root)` | Files changed outside Zed |

### Code Intelligence
| Tool | Purpose |
|---|---|
| `get_bug_correlation(file_path)` | Bug correlation analysis |
| `get_hotspots(project_root)` | Top-5 high-risk files |
| `get_repo_rank(project_root, top_k)` | PageRank for symbols |
| `cross_project_deps(project_root)` | Cross-project dependency graph |
| `find_similar_bugs(error_message)` | Similar bugs by error message |
| `predict_eta(operation)` | ETA prediction |
| `verify_action(action_type)` | Action verification |
| `generate_chunk_summaries(project_root)` | LLM summaries for chunks |

### Diagnostics (3 tools)
| Tool | Purpose |
|---|---|
| `debug_runtime_passport()` | **Process passport** — RUN_ID, PID, build, env, guard result |
| `get_runtime_counters()` | Runtime counters: calls, blocks, warnings |
| `intel_execution_timeline(limit)` | Recent action timeline with confidence |

## Project State Machine

```
UNINITIALIZED → STARTING → INDEXING → READY → FAILED
```

| Состояние | Что значит |
|---|---|
| UNINITIALIZED | Проект ещё не создан — первый вызов get_indexer не сделан |
| STARTING | Создаётся Indexer (открывается LanceDB) |
| INDEXING | Фоновая индексация запущена (chunks ещё не полные) |
| READY | Проект полностью готов |
| FAILED | Ошибка при создании/индексации |

`require_ready_project()` (через RuntimeCoordinator) ждёт READY до timeout секунд.

## SystemArtifacts — защита от feedback loop

4 уровня защиты:

1. **Directory Guard** — `.mscodebase/`, `.codebase_indices/`, `.git/`, `node_modules/`, ...
2. **Artifact Guard** — `chunk_summaries.json`, `incidents.json`, `project_memory.json`
3. **Feedback Guard** — файлы, созданные самим индексатором
4. **Embedding Guard** — финальная проверка перед эмбеддингом

Любой путь внутри `.mscodebase/` или `.codebase_indices/` = НЕ индексируется, НЕ ищется, НЕ эмбеддится.

## Mandatory Rules

**1. Intel First:** Для любых аналитических вопросов вызывай `intel_get_project_context` или `intel_get_runtime_status` — один вызов вместо 5 низкоуровневых.

**2. Project Check:** Перед search_code вызови `get_index_status`. Если `total_chunks == 0` → `intel_trigger_reindex()` (async) + `intel_get_job_status()`.

**3. Symbol Research:** Перед edit — `get_symbol_info()`. Перед рефакторингом — `impact_analysis()`.

**4. Diagnostics First:** Если tool вернул ошибку — не retry с теми же параметрами. Вызови `debug_runtime_passport()` (PID, RUN_ID, env, guard result), потом `get_logs()`.

**5. Context Budget:** Max 50 строк на `read_file`. Никогда не читай файлы целиком.

**6. Post-Modification Sync:** После `edit_file` → `notify_change(file_path=...)` + `get_index_status()`.

**7. Path Protocol:** Windows-пути (backslashes) для MCP. POSIX-пути для terminal.

**8. No Dead Tools:** `smart_search`, `deep_search`, `context_search` — DEPRECATED. Используй `search_code(mode=...)`.

**9. Async Indexing:** `intel_trigger_reindex()` → `intel_get_job_status(job_id)`:
- `completed` → можно search_code
- иначе → grep fallback

**10. Stale Code:** Если нашёл ссылку на `_SELF_INDEX_MARKER`, `.codebase_index` (без 'es'), `get_project_context` (без `intel_`) — это старый код. Обнови или удали.
