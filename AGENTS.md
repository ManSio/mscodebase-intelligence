# Global Agent Rules — MSCodeBase Hybrid Architecture (36 Registered Tools)

> Global system prompt / context injection for the AI Agent in Zed IDE. Applied across all projects.
> Optimized for the hybrid model: 10 High-Level Intelligence Tools + 26 Low-Level Core MCP Tools.

---
MSCodeBase Core Rules:

[STATE-AWARENESS]
IF get_index_status returns 0 chunks, FORBIDDEN to use search_code, switch to grep/regex.
IF chunks > 0, use search_code for semantic, get_symbol_info for exact names.

[MEMORY_PROTOCOL]
1. INITIALIZATION: При получении задачи первым делом вызови `intel_get_project_memory`. Изучи ADRs, известные проблемы и прошлые попытки.
2. CONTINUOUS LEARNING: После завершения каждой задачи вызови `intel_log_incident` с резюме: что сделано, какой подход сработал, какие ошибки возникли.
3. CONTEXT INTEGRATION: Используй данные из памяти, чтобы не повторять старые ошибки.

[SELF-CRITICISM PROTOCOL]
Перед тем как выдать финальный ответ или завершить действие:
1. ПРОВЕРКА: Проверь, нарушил ли ты правила CONTEXT BUDGET (макс. 50 строк) или SAFE WRITING (чтение перед записью).
2. АНАЛИЗ: Если результат кажется сомнительным, вызови `intel_get_runtime_status` или `get_index_status` для верификации.
3. КОРРЕКЦИЯ: Если есть ошибка — исправь её САМ, используя инструменты, не дожидаясь моей подсказки.
4. ВЕРДИКТ: Если всё верно, только тогда завершай вывод фразой "TASK VERIFIED".

[RECONNAISSANCE & EXECUTION]
NEVER guess line numbers. Use get_symbol_info or grep before read_file.
CONTEXT BUDGET: Max 50 lines per read_file call. NEVER ingest entire files.
SAFE WRITING: Read target lines again before edit. Preserve indentation and style.

[ERROR HANDLING]
Do not retry same tool with same params. Pivot to alternative.
WINDOWS PATHS: Normalize to POSIX lowercase via path.as_posix().lower().
POST-MODIFICATION: After writing, call notify_change() + get_index_status.

[CONSTRAINTS]
NO Docker, NO pytz, NO stubs, NO mocks.
STOP immediately after code block.
DO NOT REPEAT code or logic.
IF task is done, finish output.

## 0. FIRST STEP IN ANY SESSION

1. **Read the Diary:** Review the first 5 entries in `AGENT_DIARY.md` (if the file exists in the project root). This is your mandatory source of historical context regarding past sessions, implemented solutions, and recurring blockers.
2. **Determine MCP Context:**
* Scan the list of available tools for the `intel_*` prefix or core MCP tools (e.g., `search_code`).
* **If present** → You are running in Full Hybrid Context Mode. Proceed strictly to Section 1.
* **If absent** → The MCP server is offline/unavailable. Work *exclusively* using standard Zed IDE tools (`grep`, `read_file`, `terminal`). DO NOT mention, reference, or attempt to invoke MCP tools in the dialogue.


3. **Runtime Self-Check:** At the very beginning of an MCP-enabled session, invoke `intel_get_runtime_status`. If any MCP tool call fails due to pipe/transport errors, immediately treat MCP as unavailable for the remainder of the session and switch to the standard textual fallback.

---

## 1. TOOL SUBORDINATION & HYBRID SELECTION LOGIC

You must strictly separate the analytical (high-level) phase from the surgical (low-level) phase of operation using the following substitution mapping:

### 1.1 Architectural Substitution Rules

* **System & Index Health:** Instead of making separate fragmented calls to `get_index_status` or `watcher_status` for initial diagnosis, use the comprehensive **`intel_get_runtime_status`** (response time < 200ms).
* **Timeout-Safe Indexing:** You are FORBIDDEN from calling the old blocking `index_project_dir`. Always trigger **`intel_trigger_reindex`** (Fire-and-Forget). Upon receiving the `job_id`, immediately yield control back to the UI/user and poll the background progress asynchronously via **`intel_get_job_status`**.
* **Dependencies & Structural Inspection:** For a high-level architectural overview, invoke **`intel_code_topology`**. For tracking the exact call graph or definitions of a specific function/method, fall back to the low-level `get_symbol_info`.
* **Incident Post-Mortems:** When debugging runtime crashes or exceptions, instead of parsing raw logs with `get_logs`, prioritize executing **`intel_predict_root_cause`** or **`intel_analyze_incident`**.

### 1.2 Search Code Mode Matrix

`search_code(query, mode="auto")` — **единственный** инструмент для всех видов поиска.
`smart_search`, `deep_search`, `context_search` — **DEPRECATED** (будут удалены, не используй!).

| Режим | Когда использовать | Время |
|-------|------------------|-------|
| `"fast"` | Быстро найти упоминание файла/переменной/функции. Простой точный запрос. | ~300ms |
| `"quality"` (или `"smart"`) | Поиск логики, архитектуры, связей. Нужен reranker для точности. **Режим по умолчанию.** | ~1200ms |
| `"deep"` | Сложное архитектурное расследование. Многосвязный запрос. | ~2-5s |
| `"context"` | Найти похожий код по фрагменту. Передай в `query` **код**, а не текст. | ~500ms |
| `"auto"` | (По умолчанию) Автоопределение: простой запрос → fast, сложный → agentic multi-pass. | ~300ms-2s |

### 1.3 Priority Matrix

```
[ANALYSIS / BRAIN]                       [SURGICAL ACTION / HANDS]                 [BUILT-IN IDE]
High-Level Intel Tools                    Low-Level Core MCP                       Standard Zed Tools
──────────────────────                   ──────────────────────────                ────────────────
intel_get_runtime_status        ──>      get_index_status / watcher_status   ──>   (no analog)
intel_trigger_reindex           ──>      notify_change / index_project_dir   ──>   (no analog)
intel_code_topology             ──>      get_symbol_info / structural_search ──>   grep (exact match)
intel_predict_root_cause        ──>      get_logs / get_health_report        ──>   terminal cat logs
intel_get_project_memory        ──>      get_commit_history / file_history   ──>   (no analog)

```

---

## 2. COMPREHENSIVE SUBSTRATE OF AVAILABLE TOOLS (36)

### A. High-Level Intelligence Layer (10 Tools)

`intel_get_runtime_status`, `intel_trigger_reindex`, `intel_get_job_status`, `intel_code_topology`, `intel_log_incident`, `intel_analyze_incident`, `intel_add_memory_node`, `intel_get_project_memory`, `intel_get_hotspots`, `intel_predict_root_cause`.

### B. Low-Level Core MCP & Search Engine (26 Tools)

`search_code(mode)`, `structural_search`, `cross_repo_search`, `cross_project_deps`, `get_symbol_info`, `impact_analysis`, `get_repo_map`, `get_repo_rank`, `get_hotspots`, `get_bug_correlation`, `get_related_files`, `graph_query`, `get_index_status`, `get_index_progress`, `get_index_timeline`, `index_health`, `index_project_dir`, `notify_change`, `get_health_report`, `watcher_status`, `get_logs`, `get_commit_history`, `get_file_history`, `get_branch_info`, `generate_chunk_summaries`, `submit_background_task`.

> 🔄 **Deprecated** (← call `search_code` internally): `smart_search`, `deep_search`, `context_search`.

---

## 3. STRICT EXECUTION CONTRACT

* **STATE-AWARENESS:** If `intel_get_runtime_status` or `get_index_status` returns `total_chunks == 0`, semantic search pipelines (`search_code`) are **strictly forbidden**. Immediately fall back to local regex `grep` and prompt the user to fire up a background `intel_trigger_reindex`.
* **RECONNAISSANCE:** Never guess code layout, file contents, or line numbers. Always execute `intel_code_topology` or `get_symbol_info` first to localize the target, then perform precise reads.
* **CONTEXT BUDGET:** Maximum of **50 lines of code** per single built-in `read_file` call. Ingesting entire large files into the LLM context is heavily penalized. Navigate surgically.
* **WINDOWS PATHS:** You must pass file paths to all MCP tools strictly in native Windows format with escaped double backslashes (e.g., `src\\core\\config.py`).
* **POST-MODIFICATION SYNC (Commitment Chain):** Immediately after modifying any file via `edit_file` or `write_file`, you are required to invoke **`notify_change(file_path=...)`** to incrementally refresh the file's index inside the LSP VFS. If the modification fixed a bug, document its signature using `intel_log_incident`.

### notify_change() — контракт путей
- `notify_change()` принимает **относительный путь от корня проекта** или абсолютный.
- Относительные пути резолвятся через `$PROJECT_PATH` (= `$ZED_WORKTREE_ROOT`), а не от CWD.
- Примеры:
  ✅ `notify_change(file_path="src\\core\\indexer.py")`
  ✅ `notify_change(file_path="D:\\Project\\MSCodeBase\\src\\core\\indexer.py")`
  ❌ НЕ используй `$ZED_WORKTREE_ROOT` в пути — это переменная окружения, не путь.

---

## 4. AGENT DIARY CONTRACT

* **Location:** The file `AGENT_DIARY.md` must reside strictly in the workspace root directory.
* **Ingestion:** At session startup, read the top 5 entries to catch up on the project's state.
* **Emission:** Before concluding the session, prepend a new markdown entry to the **TOP** of the file (maintaining reverse-chronological order).
* **Format Structure:**

```markdown
## [YYYY-MM-DD HH:MM] — [Type: Fix|Feature|Refactor|Meta] — Title

**Problem:**
- Concise description of the issue or feature request.

**Solution:**
- High-level breakdown of the architectural edits made.

**Tools Used:** list which of the 36 tools were active during the task.
**Status:** ✅ (Completed and synchronized via `notify_change`) / ❌ (Failed/Blocked)

```

---

## 5. ABSOLUTE CRITICAL FORBIDDENS

* **FORBIDDEN** to call `smart_search`, `deep_search`, or `context_search` directly — they are DEPRECATED. Always use `search_code(query, mode=...)`.
* **FORBIDDEN** to output stubs, incomplete blocks, or code placeholders like `TODO` or `...`. Every code modification must be a fully functional, production-ready implementation.
* **FORBIDDEN** to retry the exact same tool call with identical arguments if it previously returned an error. Pivot to a fallback mechanism instead.
* **FORBIDDEN** to suggest Docker, WSL, or containerized environments. The project environment is strictly native Windows.
* **FORBIDDEN** to import the external `pytz` package for timezone calculations. Rely exclusively on the native `zoneinfo` standard library.
* **FORBIDDEN** to print debug messages or arbitrary strings to `stdout`. Any data pushed to `stdout` that does not conform to the strict JSON-RPC MCP specification will break the Zed editor parser and crash the server pipe.

---

## 6. TERMINAL TOOL WITHIN ZED (Windows Git Bash Emulation)

The built-in `terminal` execution tool inside Zed on Windows runs inside a Bash emulation layer. You must use POSIX syntax exclusively:

* ✅ `ls`, `pwd`, `cat`, `git status`, `python script.py`, `pytest`
* ❌ `dir`, `Get-ChildItem`, `type`, `copy`, `move`, `del`

---

## 7. INTERACTION STYLE

* Language: Russian (`ru-RU`). Keep interactions highly dense, technically precise, and entirely free of introductory filler or conversational fluff.
* If you spot an architectural anti-pattern or accumulating technical debt anywhere in the codebase during navigation, flag it immediately (even if unrelated to the current task) and suggest adding it to the project memory using `intel_add_memory_node` under the `tech_debt` section.
