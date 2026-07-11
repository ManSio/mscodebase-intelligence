# Project Agent Rules — MSCodeBase Hybrid Architecture (56 Registered Tools)

> Global system prompt / context injection for the AI Agent in Zed IDE. Applied across all projects.
> Optimized for the hybrid model: 14 High-Level + 39 Low-Level Core MCP + 3 Diagnostic

## 0. FIRST STEP IN ANY SESSION

1. **Read the Diary:** Review the first 5 entries in `AGENT_DIARY.md` (if the file exists in the project root).
2. **Determine MCP Context:**
   - If `intel_*` tools or `search_code` are available → Full Hybrid Context Mode.
   - If absent → MCP server offline. Work exclusively with `grep`, `read_file`, `terminal`.
3. **Runtime Check:** Call `intel_get_runtime_status`. If it fails with pipe/transport error → switch to grep/cat fallback.
4. **Load Project Memory:** Call `intel_get_project_memory()` to learn ADRs, known issues, tech debt.
5. **⚠️ MULTI-WINDOW CHECK:** `intel_get_runtime_status().project_path` — ЭТОТ проект видит MCP.
   Если пользователь говорит о ДРУГОМ проекте (лежит рядом, открыт в другом окне) —
   **НЕ ДОВЕРЯЙ** данным `get_index_status()` для этого проекта.
   Вместо этого:
   - Проверь, открыт ли проект: `ls <путь>`
   - Предупреди пользователя: «Сейчас MCP показывает проект X. Хотите, переключусь на Y?»
   - Используй `intel_explain_project_state` для проверки другого проекта

## 0.5. WORKFLOW: ИСХОДНИКИ → РАСШИРЕНИЕ ZED

### Архитектура

- **Source code:** `D:\Project\MSCodeBase` — здесь ты редактируешь код.
- **Extension dir:** `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence` — откуда MCP реально запускается.
- **Venv:** `{EXT}\venv\Scripts\python.exe` — Python со всеми пакетами.
- **llama binary:** `{EXT}\llama_msvc\` (CPU) или `{EXT}\llama_vulkan\` (GPU).
- **Models:** `{EXT}\models\` — GGUF файлы.
- **install.py** (из папки проекта) копирует файлы из исходников в расширение.

### Стандартный цикл разработки

Когда пользователь просит что-то изменить и проверить:

```
ШАГ 1 — Правим код в исходниках (D:\Project\MSCodeBase\src\)
ШАГ 2 — Синхронизируем в расширение + убиваем процессы
ШАГ 3 — Запускаем install.py для обновления
ШАГ 4 — Запускаем MCP вручную из расширения
ШАГ 5 — Тестируем (search_code, embed, rerank)
ШАГ 6 — Убиваем процессы
ШАГ 7 — Говорим пользователю: «Перезагрузи Zed»
```

### Детальный протокол

**Шаг 1 — Правка кода:**
- Редактируешь файлы в `D:\Project\MSCodeBase\src\`.
- После `edit_file` / `write_file` → `notify_change()`.
- Для переименования файлов используй `apply_file_move(old, new)` вместо `notify_change` — мета-патчинг (50ms, 0MB RAM) вместо полной переиндексации (5s, 700MB RAM).

**Шаг 2 — Синхронизация + очистка:**
```bash
# Убить старые процессы
taskkill //F //IM "llama-server.exe" 2>&1 | tail -1
taskkill //F //FI "WINDOWTITLE eq mscodebase*" //IM python.exe 2>&1 | tail -1
sleep 2

# Скопировать изменённые файлы в расширение
# (если install.py запускать не надо, а надо быстро обновить один файл)
cp /d/Project/MSCodeBase/src/core/llama_runner.py \
   "/c/Users/misha/AppData/Local/Zed/extensions/mscodebase-intelligence/src/core/llama_runner.py"
```

**Шаг 3 — install.py (если нужно обновить бинарники/модули):**
```bash
cd /d/Project/MSCodeBase && python install.py
```
Учти: install.py интерактивный (спрашивает Y/n). Если нужно авто-подтверждение:
```bash
printf 's\nn\n' | python install.py   # s=skip pip, n=skip ONNX models
```

**Шаг 4 — Запуск MCP для теста:**
```bash
cd "/c/Users/misha/AppData/Local/Zed/extensions/mscodebase-intelligence" && \
  nohup venv/Scripts/python.exe -m src.main > /tmp/mcp_test.log 2>&1 &
sleep 8   # ждём пока стартанёт embedder + reranker
```

Проверить что процессы поднялись:
```bash
tasklist //FI "IMAGENAME eq llama-server.exe" //NH 2>&1
/c/Windows/System32/netstat.exe -ano 2>&1 | grep -E ":8080 |:8081 " | grep LISTEN
```

**Шаг 5 — Тестирование:**
```python
import httpx
# Embedder
r = httpx.post('http://127.0.0.1:8080/v1/embeddings',
    json={'input': ['Тест']}, timeout=10)
print('Embed:', r.status_code, 'dim=', len(r.json()['data'][0]['embedding']))

# Reranker
r = httpx.post('http://127.0.0.1:8081/rerank',
    json={'query': 'test', 'texts': ['a', 'b']}, timeout=10)
print('Rerank:', r.status_code)

# MCP tools (если MCP запущен — они должны отвечать)
# Используй search_code, intel_get_runtime_status и т.д.
```

**Шаг 6 — Убить тестовые процессы:**
```bash
taskkill //F //IM "llama-server.exe" 2>&1
taskkill //F //FI "WINDOWTITLE eq mscodebase*" //IM python.exe 2>&1
```

**Шаг 7 — Сообщить пользователю:**
> «Готово. Перезагрузи Zed — изменения применятся.»

### Важные замечания

- **install.py шаг 4** (step_copy) копирует `llama_msvc/`, `llama_vulkan/`, `models/` ТОЛЬКО если их нет в `skip`.
  Там они уже есть в `skip`, так что install.py не затрёт бинарники — только код.
- **llama_runner.py** содержит `_start_sync()` с авто-восстановлением: если CPU DLL пропали — сам скачает
  и пропатчит. Это страховка на случай если расширение сбросилось при перезагрузке Zed.
- **Vulkan детекция** работает автоматически: если есть GPU с Vulkan и `llama_vulkan/` с бинарником —
  MCP использует GPU, иначе CPU.
- Все тесты проводи в терминале (GitBash), пути в POSIX формате (`src/core/...`).

## 1. TOOL SELECTION

### 1.1 Architectural Substitution Rules

| Instead of | Use |
|---|---|
| `get_index_status` + `watcher_status` | `intel_get_runtime_status` |
| `index_project_dir` (blocking) | `intel_trigger_reindex` (fire-and-forget) |
| Multiple low-level calls | `intel_get_project_context` (one snapshot) |
| Parsing raw logs | `intel_predict_root_cause` or `intel_analyze_incident` |

### 1.2 Search Code Mode Matrix

`search_code(query, mode="auto")` is the ONLY search tool. `smart_search`, `deep_search`, `context_search` are DEPRECATED.

| Mode | When | Speed |
|---|---|---|
| `"fast"` | Exact file/variable name lookup | ~300ms |
| `"quality"` | Logic, architecture, relationships (default) | ~1200ms |
| `"deep"` | Complex architectural investigation | ~2-5s |
| `"context"` | Find similar code by code fragment | ~500ms |
| `"auto"` | Auto-detect: simple→fast, complex→agentic | ~300ms-2s |

### 1.3 Priority Matrix

```
[ANALYSIS / BRAIN]                  [SURGICAL ACTION]               [FALLBACK]
High-Level Intel Tools              Low-Level Core MCP              Built-in IDE
──────────────────────              ──────────────────────          ───────────
intel_get_runtime_status      ──>   get_index_status / watcher     grep (exact)
intel_trigger_reindex         ──>   notify_change                  grep (fallback)
intel_code_topology           ──>   get_symbol_info / structural   grep
intel_predict_root_cause      ──>   get_logs / get_health_report   terminal cat
intel_get_project_memory      ──>   get_commit_history / file_hist (no analog)
intel_get_project_context     ──>   (aggregates 5+ calls)
```

## 2. AVAILABLE TOOLS (56)

### A. High-Level Intelligence Layer (14 tools)

`intel_get_runtime_status`, `intel_trigger_reindex`, `intel_get_job_status`,
`intel_code_topology`, `intel_log_incident`, `intel_analyze_incident`,
`intel_add_memory_node`, `intel_get_project_memory`, `intel_get_project_context`,
`intel_explain_project_state`, `intel_predict_root_cause`, `intel_get_hotspots`,
`intel_get_telemetry`, `intel_tool_health`.

Diagnostic: `debug_runtime_passport`, `get_runtime_counters`, `intel_execution_timeline`.

### B. Low-Level Core MCP & Search (39 tools)

`search_code(mode=fast|quality|deep|context|auto)`, `cross_repo_search`,
`cross_project_deps`, `get_symbol_info`, `impact_analysis`, `get_repo_map`,
`get_repo_rank`, `get_hotspots`, `get_bug_correlation`, `get_related_files`,
`graph_query`, `get_index_status`, `get_index_progress`, `get_index_timeline`,
`index_health`, `index_project_dir`, `notify_change`, `watcher_status`,
`get_logs`, `get_health_report`, `run_health_check`, `get_commit_history`,
`get_file_history`, `get_branch_info`, `generate_chunk_summaries`,
`scan_changes`, `find_similar_bugs`, `predict_eta`, `verify_action`,
`get_task_status`, `submit_background_task`, `read_live_file`,
`structural_search`.

`ack_impact(file_path)`, `rename_symbol(old, new, apply)`,
`move_symbol(symbol, to_file, apply)`, `safe_delete(symbol, force, apply)`,
`replace_symbol(symbol, new_code, apply)`,
`insert_before/after_symbol(anchor, new_code, apply)`.

> **Deprecated** (use `search_code`): `smart_search`, `deep_search`, `context_search`.

### C. Write Tools (6)

`rename_symbol(old, new, apply)` — rename symbol across all files
`move_symbol(symbol, to_file, apply)` — move symbol to another file
`safe_delete(symbol, force, apply)` — safe delete with reference check
`replace_symbol(symbol, new_code, apply)` — replace function/class body
`insert_before/after_symbol(anchor, new_code, apply)` — anchor-based insertion
`ack_impact(file_path)` — acknowledge impact for modification guard

## 3. STATE AWARENESS

- If `get_index_status` returns 0 chunks → FORBIDDEN to use `search_code`. Switch to `grep`/regex.
- If chunks > 0 → use `search_code` for semantic, `get_symbol_info` for exact names.
- If using write tools, call `ack_impact(file_path)` before destructive operations on load-bearing files.

## 4. MEMORY PROTOCOL

1. **Start:** Call `intel_get_project_memory()`. Study ADRs, known issues, past attempts.
2. **After task:** Call `intel_log_incident()` with component, symptom, root_cause, fix, success.
3. **If you notice an anti-pattern:** Call `intel_add_memory_node(section="tech_debt", data_json=...)`.

## 5. EXECUTION CONTRACT

### Reconnaissance
- NEVER guess line numbers. Use `get_symbol_info` or `grep` before `read_file`.
- CONTEXT BUDGET: Max 50 lines per `read_file` call. NEVER ingest entire files.
- SAFE WRITING: Read target lines before edit. Preserve indentation and style.

### Post-Modification
After `edit_file` / `write_file` → `notify_change(file_path=...)` → `get_index_status()`.
Use batch notify: `notify_change(file_path=["src/a.py", "src/b.py"])`.
For file renames, use `apply_file_move(old, new)` instead of `notify_change` — it does meta-patching in 50ms instead of full reindex (5s).

### Error Handling
- Do not retry same tool with same params. Pivot to alternative.
- If MCP fails → grep/cat → find_path → terminal.
- After failed hypothesis twice → STOP. Pivot to different hypothesis.

### Windows Paths
- MCP tools: Windows escaped format (`src\\core\\config.py`).
- Terminal (GitBash): POSIX format (`src/core/config.py`).

## 6. ABSOLUTE FORBIDDENS

### Deprecated
- `smart_search`, `deep_search`, `context_search` — DEPRECATED. Use `search_code(mode=...)`.
- `index_project_dir` (blocking) — Use `intel_trigger_reindex` (async).

### Architecture
- Tools must NOT call Registry, Bridge, or Passport directly. Use `RuntimeCoordinator.can_execute()` + `ProjectContext.capture()`.
- RuntimeCoordinator must NOT know about Search, Indexer, or Memory.
- New components must answer: "Which existing layer does it extend?"
- One class = one responsibility.

### Environment
- NO Docker, NO WSL, NO pytz (use zoneinfo).
- NO stubs, TODOs, or placeholders. Every change = production-ready.
- NO debug prints to stdout (breaks JSON-RPC parser).
- NO investigating a hypothesis after two consecutive observations confirm the same fact.

## 7. SELF-CHECK BEFORE COMPLETING

1. Did I update the index after writing? (`notify_change` + `get_index_status`)
2. Are paths in correct format? (Windows for MCP, POSIX for terminal)
3. Did I avoid retrying failed tools?
4. Is the code production-ready (no stubs/TODOs)?
5. Did I update `AGENT_DIARY.md`?
6. Did I log the incident in project memory? (`intel_log_incident`)
7. Did I check `diagnostics`?
8. Did I run `python -m pytest tests/ -k write_tools -v` before committing?
9. All correct? → **TASK VERIFIED**
