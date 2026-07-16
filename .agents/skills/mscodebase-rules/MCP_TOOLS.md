# Полный справочник MCP-инструментов MSCodeBase (36 шт.)

> **Для AI-агента.** Источник правды по регистрации: `src/mcp/server.py` + `src/core/intelligence_layer.py`.
> Если инструмента нет там — его не существует.

**Главное:** MCP = **Tool name** + **JSON Raw Input**. Не shell. Не `func()`.

---

## JSON Raw Input — эталонные примеры (Zed)

### Без аргументов → `{}`

| Tool | Raw Input |
|------|-----------|
| `debug_runtime_passport` | `{}` |
| `intel_get_runtime_status` | `{}` |
| `intel_trigger_reindex` | `{}` |
| `intel_get_project_memory` | `{}` |
| `intel_explain_project_state` | `{}` |
| `intel_get_hotspots` | `{}` |
| `get_runtime_counters` | `{}` |

### С аргументами → JSON-поля

**search_code:**
```json
{
  "query": "ETA estimated_seconds reindex job progress",
  "mode": "fast"
}
```

**intel_get_job_status:**
```json
{
  "job_id": "24fc56ed"
}
```

**get_symbol_info:**
```json
{
  "query": "watchdog_status"
}
```

**read_live_file:**
```json
{
  "file_path": "src\\core\\indexer.py"
}
```

**intel_log_incident:**
```json
{
  "component": "indexer",
  "symptom": "watchdog false alarm",
  "root_cause": "heartbeat init 0.0",
  "fix": "init to time.time()",
  "success": true
}
```

**notify_change:**
```json
{
  "file_path": "src\\core\\indexer.py"
}
```

**intel_explain_project_state** (опционально project_root):
```json
{
  "project_root": ""
}
```

---

## MCP-FIRST: работай через MCP, не через IDE

**Если MCP online (`intel_get_runtime_status` OK) — все исследования только через MCP.**

| Задача | MCP-инструмент |
|--------|----------------|
| Поиск по смыслу | `search_code(mode="quality")` |
| Точное имя | `search_code(mode="fast")` |
| Символ / call graph | `get_symbol_info` |
| Архитектура | `intel_code_topology`, `impact_analysis` |
| Прочитать файл | `read_live_file` |
| Диагностика | `intel_explain_project_state`, `get_health_report` |
| Git | `get_commit_history`, `get_file_history` |
| Data flow | `get_variable_flow` |

**Fallback на grep/read** — только если: MCP offline, chunks=0, или 2 fail подряд.

---

## A. High-Level Intelligence (15 инструментов)

| Инструмент | Аргументы | Когда использовать |
|-----------|-----------|-------------------|
| `intel_get_runtime_status` | — | Проверка здоровья системы (первый вызов в сессии) |
| `intel_trigger_reindex` | — | Запуск переиндексации (возвращает `job_id`) |
| `intel_get_job_status` | `job_id: str` | Опрос прогресса задачи по ID |
| `intel_get_project_memory` | — | Загрузка ADR / known_issues / tech_debt |
| `intel_log_incident` | `component, symptom, root_cause, fix, success` | Запись инцидента после задачи |
| `intel_add_memory_node` | `section: str, data_json: str` | Добавить узел памяти (adrs / tech_debt / …) |
| `intel_get_project_context` | `project_root: str = ""` | Полный снэпшот состояния проекта |
| `intel_explain_project_state` | `project_root: str = ""` | Человекочитаемый диагноз (READY / Blocked) |
| `intel_predict_root_cause` | `error_message: str, component_context: str = None` | Предсказание причины сбоя |
| `intel_analyze_incident` | `error_message: str` | Поиск похожих инцидентов из памяти |
| `intel_code_topology` | `symbol_name: str` | Граф вызовов для символа |
| `intel_get_hotspots` | — | Топ-5 файлов с highest risk density |
| `intel_get_telemetry` | `days: int = 7` | Таблица телеметрии (runtime + per-tool) |
| `intel_tool_health` | — | Панель здоровья инструментов (успех / латентность) |
| `intel_auto_collect_adrs` | `max_commits: int = 50` | Сбор ADR из git-лога |

**Пример правильной цепочки:**

```
intel_trigger_reindex()           →  job_id="24fc56ed"
intel_get_job_status(job_id="24fc56ed")  →  опрос прогресса
```

---

## B. Core MCP & Search (19 инструментов)

### Поиск (1 инструмент — единственный!)

| Инструмент | Аргументы | Когда |
|-----------|-----------|------|
| `search_code` | `query: str, mode: str = "auto", limit: int = 6` | **ВСЕ** виды поиска. Режимы: `fast` / `quality` / `deep` / `context` / `auto` |

> **DEPRECATED:** `smart_search`, `deep_search`, `context_search` — использовать только `search_code(mode=...)`.

### Анализ кода

| Инструмент | Аргументы |
|-----------|-----------|
| `get_symbol_info` | `query: str` |
| `get_variable_flow` | `name: str, scope_id: str = None` |
| `impact_analysis` | `symbol: str, depth: int = 3` |
| `cross_repo_search` | `query: str` |
| `cross_project_deps` | `project_root: str = ""` |
| `get_repo_map` | `project_root: str = ""` |
| `get_repo_rank` | `project_root: str = ""` |
| `get_hotspots` | `project_root: str = ""` |
| `get_bug_correlation` | `file_path: str` |
| `get_related_files` | `file_path: str` |
| `graph_query` | `query: str` |
| `query_graph` | `cypher_query: str` (Cypher over PropertyGraph) |
| `structural_search` | `pattern: str, project_root: str = ""` |

### Индекс / состояние

| Инструмент | Аргументы |
|-----------|-----------|
| `get_index_status` | `project_root: str = ""` |
| `get_index_progress` | — |
| `get_index_timeline` | — |
| `index_health` | `project_root: str = ""` |
| `index_project_dir` | `path: str` (**BLOCKING — НЕ использовать!**) |
| `notify_change` | `file_path: str` или `list[str]` |
| `watcher_status` | — |

### Логи / здоровье / git

| Инструмент | Аргументы |
|-----------|-----------|
| `get_logs` | — |
| `get_health_report` | `project_root: str = ""` |
| `run_health_check` | — |
| `get_commit_history` | `project_root: str = "", limit: int = 20` |
| `get_file_history` | `file_path: str` |
| `get_branch_info` | `project_root: str = ""` |
| `generate_chunk_summaries` | `project_root: str = ""` |
| `scan_changes` | `project_root: str = ""` |
| `find_similar_bugs` | `error_message: str` |
| `predict_eta` | `operation: str` |
| `verify_action` | `action_type: str` |
| `get_task_status` | `job_id: str` |
| `submit_background_task` | `task_type: str` |
| `read_live_file` | `file_path: str` |

### Write-инструменты (7 шт.)

| Инструмент | Аргументы |
|-----------|-----------|
| `rename_symbol` | `old_name: str, new_name: str, file_path: str = "", apply: bool = False` |
| `move_symbol` | `symbol: str, to_file: str, apply: bool = False` |
| `safe_delete` | `symbol: str, force: bool = False, apply: bool = False` |
| `replace_symbol` | `symbol: str, new_code: str, apply: bool = False` |
| `insert_before_symbol` | `anchor: str, new_code: str, apply: bool = False` |
| `insert_after_symbol` | `anchor: str, new_code: str, apply: bool = False` |
| `ack_impact` | `file_path: str` |

---

## C. Diagnostic (3 инструмента)

| Инstrument | Аргументы | Когда |
|-----------|-----------|-------|
| **`debug_runtime_passport`** | — | **ПЕРВЫЙ вызов сессии.** Проверка MCP pipe: RUN_ID, BUILD_ID, PID, ext_root. Transport error = MCP offline |
| `get_runtime_counters` | — | Счётчики: calls, blocks, warnings |
| `intel_execution_timeline` | `limit: int = 15` | Лента последних действий |

> **Важно:** `intel_get_runtime_status` — про embedder/индекс, **не** про связь с MCP.
> Связь проверяет только `debug_runtime_passport`.

---

## Правильный паттерн использования

**❌ НЕПРАВИЛЬНО (одна строка, 3 команды):**

```
intel_trigger_reindex(); intel_get_job_status(); search_code("foo")
```

Это не сработает — парсер ожидает **один** вызов за раз.

**❌ НЕПРАВИЛЬНО (параллельный залп 3+ MCP):**

```
intel_get_project_context + intel_get_hotspots + get_health_report  (одновременно)
```

→ таймауты и прерывания.

**✅ ПРАВИЛЬНО (последовательные вызовы):**

```
1. intel_get_runtime_status()              → система готова?
2. intel_get_project_memory()              → ADR, known issues
3. intel_explain_project_state()           → один снэпшот
4. intel_trigger_reindex()                   → job_id
5. intel_get_job_status(job_id="…")          → опрос (повторять по poll_interval)
6. search_code(query="foo", mode="quality")  → после READY / completed
```

**Ключевое правило:** каждый вызов — отдельный tool call. Результат предыдущего → аргументы следующего.

---

## Сессия: минимальный протокол

```
intel_get_runtime_status
    ↓
intel_get_project_memory
    ↓
intel_explain_project_state   (или intel_get_project_context — один раз)
    ↓
get_index_status              (если chunks == 0 → intel_trigger_reindex)
    ↓
search_code / get_symbol_info / grep
    ↓
после edit → notify_change → get_index_status
```

---

## Intel First (замена low-level)

| Вместо | Использовать |
|--------|--------------|
| `get_index_status` + `watcher_status` | `intel_get_runtime_status` |
| 5+ low-level вызовов | `intel_get_project_context` |
| `index_project_dir` (blocking) | `intel_trigger_reindex` + `intel_get_job_status` |
| парсинг логов вручную | `intel_predict_root_cause` / `intel_analyze_incident` |
